#!/usr/bin/env python3
"""
Subscribe to robot camera (sensor_msgs/Image) + onboard audio (audio_common_msgs/AudioData),
align audio to the *camera message timeline* using Image.header.stamp deltas, and write:

  <output_root>/<session_id>/whole_video.mp4
  <output_root>/<session_id>/audio.wav

AudioData has no header; alignment uses consecutive Image.header.stamp deltas (see module doc).

Params (~):
  session_id, camera_topic, audio_topic
  sample_rate, channels, sample_width
  warmup_seconds
  use_image_stamp
  output_root     — __auto__: $PERCY_DATA_DIR or <workspace>/src/DATA
  video_fps_fallback  — 仅当无法用 stamp/wall 估计帧间隔时作为 1/dt 回退；写入 MP4 的 fps 优先用当前帧 dt 的倒数（与音频切片一致）
  video_fourcc_preference — 逗号分隔四字符编码，依次尝试（默认 avc1,H264,mp4v），提高播放器兼容性
  video_transcode_h264    — 录制结束后用 ffmpeg 转成 H.264（浏览器/VLC 兼容；默认 true）
  video_fix_timeline      — 按首尾 Image.stamp 校正 MP4 帧率，使视频时长≈音频（默认 true）
  video_ffmpeg_path       — ffmpeg 可执行文件路径（默认 ffmpeg）
  video_ffprobe_path      — ffprobe 可执行文件路径（默认 ffprobe）
"""
from __future__ import print_function

import json
import os
import subprocess
import sys
import threading

import cv2
import rospy
from audio_common_msgs.msg import AudioData
from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image


def _default_output_root(script_file):
    env = os.environ.get("PERCY_DATA_DIR")
    if env:
        return env
    # src/percy/scripts/ -> workspace src/DATA
    src_dir = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(script_file)), "..", "..")
    )
    return os.path.join(src_dir, "DATA")


class StampAlignedRecorder(object):
    def __init__(self):
        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._audio_buf = bytearray()

        self._session = str(rospy.get_param("~session_id", rospy.get_param("~id", "0")))
        self._camera_topic = rospy.get_param(
            "~camera_topic", "/head_front_camera/color/image_raw"
        )
        self._audio_topic = rospy.get_param("~audio_topic", "/audio/channel0")
        self._sample_rate = int(rospy.get_param("~sample_rate", 16000))
        self._channels = int(rospy.get_param("~channels", 1))
        self._sample_width = int(rospy.get_param("~sample_width", 2))
        self._warmup = float(rospy.get_param("~warmup_seconds", 0.5))
        self._use_image_stamp = bool(rospy.get_param("~use_image_stamp", True))
        self._fps_fallback = float(rospy.get_param("~video_fps_fallback", 30.0))

        out_root_param = rospy.get_param("~output_root", "__auto__")
        if not out_root_param or out_root_param == "__auto__":
            out_root = _default_output_root(__file__)
        else:
            out_root = out_root_param
        self._out_dir = os.path.join(out_root, self._session)
        os.makedirs(self._out_dir, exist_ok=True)
        self._wav_path = os.path.join(self._out_dir, "audio.wav")
        self._mp4_path = os.path.join(self._out_dir, "whole_video.mp4")
        self._meta_path = os.path.join(self._out_dir, "recording_meta.json")

        self._wf = None
        self._writer = None
        self._frame_size = None

        self._both_seen = False
        self._warmup_done = False
        self._warmup_start = None
        self._had_audio = False
        self._had_image = False

        self._recording = False
        self._shutting_down = False
        self._last_img_wall = None
        self._last_img_stamp = None
        self._frame_count = 0
        self._first_stamp = None
        self._last_stamp = None
        self._video_fourcc_used = None

        rospy.loginfo("percy: session=%s out_dir=%s", self._session, self._out_dir)
        rospy.loginfo(
            "ROS_MASTER_URI=%s ROS_IP=%s",
            os.environ.get("ROS_MASTER_URI", ""),
            os.environ.get("ROS_IP", ""),
        )
        rospy.loginfo(
            "camera=%s audio=%s stamp_align=%s",
            self._camera_topic,
            self._audio_topic,
            self._use_image_stamp,
        )

        self._audio_sub = rospy.Subscriber(
            self._audio_topic, AudioData, self._audio_cb, queue_size=200, buff_size=2**24
        )
        self._image_sub = rospy.Subscriber(
            self._camera_topic, Image, self._image_cb, queue_size=30, buff_size=2**24
        )
        rospy.on_shutdown(self._shutdown)
        rospy.loginfo(
            "Node running: this process blocks until Ctrl+C (normal for roslaunch). "
            "Expect logs: both streams -> %.1fs warmup -> Recording -> ...",
            self._warmup,
        )
        rospy.Timer(rospy.Duration(3.0), self._timer_waiting, oneshot=False)

    def _timer_waiting(self, _event):
        if self._recording:
            return
        rospy.loginfo(
            "status: had_image=%s had_audio=%s warmup_done=%s (need both topics before warmup)",
            self._had_image,
            self._had_audio,
            self._warmup_done,
        )

    def _audio_cb(self, msg):
        with self._lock:
            self._audio_buf.extend(msg.data)
            self._had_audio = True

    def _clear_audio_buf(self):
        with self._lock:
            self._audio_buf.clear()

    def _pop_audio(self, nbytes):
        out = bytearray()
        with self._lock:
            take = min(len(self._audio_buf), nbytes)
            if take:
                out.extend(self._audio_buf[:take])
                del self._audio_buf[:take]
        if len(out) < nbytes:
            out.extend(b"\x00" * (nbytes - len(out)))
        return bytes(out)

    def _open_wav(self):
        import wave

        self._wf = wave.open(self._wav_path, "wb")
        self._wf.setnchannels(self._channels)
        self._wf.setsampwidth(self._sample_width)
        self._wf.setframerate(self._sample_rate)

    def _open_writer(self, frame_wh, fps=None):
        w, h = frame_wh
        # 容器时间轴须接近真实帧率，否则「音频按 stamp 切片」与「视频按固定 30fps」时长会差一个数量级
        if fps is not None and fps > 0:
            fps_out = float(fps)
        else:
            fps_out = max(self._fps_fallback, 1.0)
        fps_out = max(0.25, min(fps_out, 120.0))

        pref = rospy.get_param("~video_fourcc_preference", "avc1,H264,mp4v")
        fourcc_names = [s.strip() for s in str(pref).split(",") if s.strip()]
        self._writer = None
        last_err = None
        for name in fourcc_names:
            if len(name) != 4:
                continue
            try:
                fourcc = cv2.VideoWriter_fourcc(*name)
            except Exception as e:
                last_err = e
                continue
            wri = cv2.VideoWriter(self._mp4_path, fourcc, fps_out, (w, h))
            if wri.isOpened():
                self._writer = wri
                self._video_fourcc_used = name
                rospy.loginfo("VideoWriter fourcc=%s fps=%.4f", name, fps_out)
                break
            last_err = "not opened"
        if self._writer is None:
            rospy.logfatal(
                "Failed to open VideoWriter for %s (tried %s, last=%s)",
                self._mp4_path,
                fourcc_names,
                last_err,
            )
            raise SystemExit(1)

    def _dt_for_frame(self, stamp_curr):
        """Seconds of audio to associate with this frame."""
        dt = None
        if self._use_image_stamp and self._last_img_stamp is not None:
            dt = (stamp_curr - self._last_img_stamp).to_sec()

        if dt is None or dt <= 0.0:
            if self._last_img_wall is not None:
                dt = (rospy.Time.now() - self._last_img_wall).to_sec()
            else:
                dt = 1.0 / self._fps_fallback

        if dt <= 0.0:
            dt = 1.0 / self._fps_fallback

        return dt

    def _image_cb(self, msg):
        if self._shutting_down:
            return
        self._had_image = True
        stamp = msg.header.stamp

        if not self._both_seen:
            if self._had_audio and self._had_image:
                self._both_seen = True
                self._warmup_start = rospy.Time.now()
                rospy.loginfo("Both streams seen; warmup %.3f s", self._warmup)
            else:
                return

        if self._both_seen and not self._warmup_done:
            if (rospy.Time.now() - self._warmup_start).to_sec() >= self._warmup:
                self._warmup_done = True
                self._clear_audio_buf()
                # 保留本帧 stamp，使「下一帧」的 dt 为真实帧间隔；勿置 None（否则首帧 dt=1/fps_fallback、MP4 时间轴与音频严重错位）
                self._last_img_stamp = stamp
                self._last_img_wall = rospy.Time.now()
                rospy.loginfo("Warmup finished; recording starts on next frame.")
            return

        if not self._warmup_done:
            return

        try:
            bgr = self._bridge.imgmsg_to_cv2(msg, "bgr8")
        except CvBridgeError as e:
            rospy.logerr("cv_bridge: %s", e)
            return

        h, w = bgr.shape[:2]
        dt = self._dt_for_frame(stamp)
        nbytes = int(
            round(
                float(dt)
                * float(self._sample_rate)
                * float(self._channels)
                * float(self._sample_width)
            )
        )
        nbytes = max(nbytes, 1)

        if not self._recording:
            self._open_wav()
            fps_from_dt = 1.0 / max(dt, 1e-4)
            self._open_writer((w, h), fps=fps_from_dt)
            self._recording = True
            self._first_stamp = stamp.to_sec()
            self._write_meta_live(finalize_status="recording")
            rospy.loginfo("Recording -> %s , %s", self._wav_path, self._mp4_path)

        pcm = self._pop_audio(nbytes)
        if self._wf is None:
            return
        self._wf.writeframes(pcm)

        if self._frame_size is not None and (w, h) != self._frame_size:
            rospy.logwarn("Frame size changed; re-opening video writer.")
            self._writer.release()
            self._open_writer((w, h), fps=1.0 / max(dt, 1e-4))

        self._writer.write(bgr)
        self._frame_count += 1
        self._frame_size = (w, h)
        self._last_img_wall = rospy.Time.now()
        self._last_img_stamp = stamp
        self._last_stamp = stamp.to_sec()

    def _probe_video_codec(self):
        ffprobe = str(rospy.get_param("~video_ffprobe_path", "ffprobe"))
        try:
            out = subprocess.check_output(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "csv=p=0",
                    self._mp4_path,
                ],
                stderr=subprocess.STDOUT,
                timeout=30,
            )
            return out.decode().strip()
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as e:
            rospy.logwarn("ffprobe failed for %s: %s", self._mp4_path, e)
            return None

    def _write_meta_live(self, finalize_status="recording"):
        """Write partial meta so turn_dialogue can lock timeline origin early."""
        meta = {
            "session_id": self._session,
            "camera_topic": self._camera_topic,
            "audio_topic": self._audio_topic,
            "use_image_stamp": self._use_image_stamp,
            "frames": self._frame_count,
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "sample_width": self._sample_width,
            "first_image_stamp": self._first_stamp,
            "last_image_stamp": self._last_stamp,
            "wav": self._wav_path,
            "mp4": self._mp4_path,
            "finalize_status": finalize_status,
        }
        try:
            with open(self._meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            rospy.logwarn("Could not write live meta: %s", e)

    def _stamp_span_fps(self):
        """Average FPS from image header stamps (matches audio slice timeline)."""
        if self._frame_count < 2 or self._first_stamp is None or self._last_stamp is None:
            return None
        span = float(self._last_stamp - self._first_stamp)
        if span <= 1e-3:
            return None
        fps = float(self._frame_count) / span
        return max(0.25, min(fps, 120.0))

    def _spawn_finalize_background(self, meta):
        """Detached ffmpeg so roslaunch SIGTERM (~15s) does not kill long finalize."""
        if self._frame_count <= 0 or not os.path.isfile(self._mp4_path):
            return

        script_dir = os.path.dirname(os.path.abspath(__file__))
        helper = os.path.join(script_dir, "finalize_recording.py")
        if not os.path.isfile(helper):
            rospy.logwarn("finalize_recording.py not found; MP4 may not match audio duration")
            return

        done_path = os.path.join(self._out_dir, "finalize.done")
        log_path = os.path.join(self._out_dir, "finalize.log")
        for p in (done_path, self._mp4_path + ".finalize.tmp.mp4"):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass

        span = meta.get("video_stamp_span_sec") or 0.0
        rospy.loginfo(
            "Finalize queued (background): span=%.1fs frames=%d — roslaunch 会先退出，请等待完成",
            span,
            self._frame_count,
        )
        rospy.loginfo("  log: tail -f %s", log_path)
        rospy.loginfo(
            "  wait: bash %s/wait_finalize.sh %s",
            script_dir,
            self._out_dir,
        )

        with open(log_path, "w") as logf:
            subprocess.Popen(
                [sys.executable, helper, self._meta_path],
                stdout=logf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )

    def _shutdown(self):
        self._shutting_down = True
        try:
            self._image_sub.unregister()
        except Exception:
            pass
        try:
            self._audio_sub.unregister()
        except Exception:
            pass
        if self._wf is not None:
            try:
                self._wf.close()
            except Exception:
                pass
            self._wf = None
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None

        stamp_span = None
        if self._first_stamp is not None and self._last_stamp is not None:
            stamp_span = float(self._last_stamp - self._first_stamp)

        meta = {
            "session_id": self._session,
            "camera_topic": self._camera_topic,
            "audio_topic": self._audio_topic,
            "use_image_stamp": self._use_image_stamp,
            "frames": self._frame_count,
            "sample_rate": self._sample_rate,
            "channels": self._channels,
            "sample_width": self._sample_width,
            "first_image_stamp": self._first_stamp,
            "last_image_stamp": self._last_stamp,
            "wav": self._wav_path,
            "mp4": self._mp4_path,
            "video_fourcc_used": self._video_fourcc_used,
            "video_transcode_h264": bool(
                rospy.get_param("~video_transcode_h264", True)
            ),
            "video_fix_timeline": bool(rospy.get_param("~video_fix_timeline", True)),
            "video_finalize_preset": str(
                rospy.get_param("~video_finalize_preset", "medium")
            ),
            "video_finalize_ultrafast_sec": float(
                rospy.get_param("~video_finalize_ultrafast_sec", 120.0)
            ),
            "video_finalize_timeout_sec": int(
                rospy.get_param("~video_finalize_timeout_sec", 7200)
            ),
            "video_ffmpeg_path": str(rospy.get_param("~video_ffmpeg_path", "ffmpeg")),
            "video_ffprobe_path": str(
                rospy.get_param("~video_ffprobe_path", "ffprobe")
            ),
            "video_stamp_span_sec": stamp_span,
            "finalize_status": "pending",
        }
        try:
            with open(self._meta_path, "w") as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            rospy.logwarn("Could not write meta: %s", e)

        self._spawn_finalize_background(meta)

        rospy.loginfo(
            "Recording stopped. frames=%d wav=%s mp4=%s (finalize in background)",
            self._frame_count,
            self._wav_path,
            self._mp4_path,
        )


def main():
    import sys

    print("[percy] starting stamp_aligned_recorder (before rospy.init)...", file=sys.stderr, flush=True)
    rospy.init_node("stamp_aligned_recorder", anonymous=False)
    print("[percy] rospy.init_node done, loading node...", file=sys.stderr, flush=True)
    StampAlignedRecorder()
    rospy.loginfo("rospy.spin(): press Ctrl+C to stop and write recording_meta.json")
    rospy.spin()


if __name__ == "__main__":
    main()
