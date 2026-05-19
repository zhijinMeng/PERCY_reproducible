#!/usr/bin/env python3
"""
Publish AudioData from host USB mic (RØDE NT-USB+) via ALSA.

Use ffmpeg to negotiate sample format (avoids S16_LE mis-read hiss on USB mics).
Fallback: arecord at native rate + audioop resample.

  roslaunch percy host_rode_capture.launch
"""
from __future__ import print_function

import audioop
import os
import shutil
import subprocess
import sys
import threading

import rospy
from audio_common_msgs.msg import AudioData

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from host_usb_mic_detect import detect_host_usb_mic  # noqa: E402


class HostRodeCapture(object):
    def __init__(self):
        rospy.init_node("host_rode_capture")
        auto = str(rospy.get_param("~auto_detect_device", "true")).lower() in ("1", "true", "yes")
        device = str(rospy.get_param("~alsa_device", "auto"))
        if auto or device in ("", "auto"):
            found = detect_host_usb_mic()
            device = found if found else ""
            if not device:
                rospy.logwarn(
                    "host_rode_capture: no USB mic; plug in Rode (respawn will retry)"
                )
        self._device = device
        self._backend = str(rospy.get_param("~capture_backend", "ffmpeg")).strip().lower()
        self._cap_rate = int(rospy.get_param("~capture_sample_rate", 48000))
        self._cap_channels = int(rospy.get_param("~capture_channels", 2))
        self._out_rate = int(rospy.get_param("~sample_rate", 16000))
        self._gain = float(rospy.get_param("~gain", 1.0))
        self._topic = str(rospy.get_param("~topic", "/audio/rode"))
        chunk_ms = float(rospy.get_param("~chunk_ms", 100.0))
        self._out_chunk_bytes = max(320, int(self._out_rate * 2 * chunk_ms / 1000.0))
        self._read_bytes = max(
            640,
            int(self._cap_rate * 2 * self._cap_channels * chunk_ms / 1000.0),
        )
        self._pub = rospy.Publisher(self._topic, AudioData, queue_size=20)
        self._proc = None
        self._thread = None
        self._stop = threading.Event()
        self._ratecv_state = None
        self._pcm_buf = bytearray()

    def start(self):
        if not self._device:
            rospy.logfatal("No ALSA device; set ~alsa_device or plug in Rode USB mic")
            return False
        if self._backend == "ffmpeg" and shutil.which("ffmpeg"):
            ok = self._start_ffmpeg()
        else:
            if self._backend == "ffmpeg":
                rospy.logwarn("ffmpeg not found; falling back to arecord")
            ok = self._start_arecord()
        if not ok:
            return False
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return True

    def _start_ffmpeg(self):
        # Let ffmpeg negotiate HW format; output 16 kHz mono s16le.
        # 立体声混为 mono，避免只采到单声道
        af_parts = ["pan=mono|c0=0.5*c0+0.5*c1"]
        g = min(max(self._gain, 0.0), 8.0)
        if abs(g - 1.0) > 1e-6:
            af_parts.append("volume=%f" % g)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "alsa",
            "-i",
            self._device,
            "-af",
            ",".join(af_parts),
            "-ac",
            "1",
            "-ar",
            str(self._out_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            rospy.logerr("ffmpeg failed: %s", e)
            return False
        self._read_bytes = self._out_chunk_bytes
        rospy.loginfo(
            "host_rode_capture: backend=ffmpeg device=%s -> %dHz mono topic=%s chunk=%d",
            self._device,
            self._out_rate,
            self._topic,
            self._out_chunk_bytes,
        )
        return True

    def _start_arecord(self):
        cmd = [
            "arecord",
            "-D",
            self._device,
            "-f",
            "S16_LE",
            "-r",
            str(self._cap_rate),
            "-c",
            str(self._cap_channels),
            "-t",
            "raw",
            "-q",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as e:
            rospy.logerr("arecord failed: %s", e)
            return False
        rospy.loginfo(
            "host_rode_capture: backend=arecord device=%s cap=%dHz/%dch -> %dHz mono",
            self._device,
            self._cap_rate,
            self._cap_channels,
            self._out_rate,
        )
        return True

    def _process_arecord(self, raw):
        if not raw:
            return b""
        width = 2
        if self._cap_channels >= 2:
            raw = audioop.tomono(raw, width, 0.5, 0.5)
        if self._cap_rate != self._out_rate:
            raw, self._ratecv_state = audioop.ratecv(
                raw, width, 1, self._cap_rate, self._out_rate, self._ratecv_state
            )
        if self._gain != 1.0:
            raw = audioop.mul(raw, width, min(max(self._gain, 0.0), 4.0))
        return raw

    def _publish_pcm(self, pcm):
        if self._gain != 1.0 and self._backend == "ffmpeg":
            pass  # gain applied in ffmpeg
        elif self._gain != 1.0:
            pcm = audioop.mul(pcm, 2, min(max(self._gain, 0.0), 4.0))
        self._pcm_buf.extend(pcm)
        while len(self._pcm_buf) >= self._out_chunk_bytes:
            chunk = bytes(self._pcm_buf[: self._out_chunk_bytes])
            del self._pcm_buf[: self._out_chunk_bytes]
            msg = AudioData()
            msg.data = chunk
            self._pub.publish(msg)

    def _read_loop(self):
        assert self._proc is not None and self._proc.stdout is not None
        while not self._stop.is_set() and not rospy.is_shutdown():
            raw = self._proc.stdout.read(self._read_bytes)
            if not raw:
                err = ""
                if self._proc.stderr:
                    err = self._proc.stderr.read().decode("utf-8", errors="replace")
                rospy.logerr("capture ended (stderr: %s)", err.strip() or "none")
                break
            if self._backend == "ffmpeg":
                self._publish_pcm(raw)
            else:
                self._publish_pcm(self._process_arecord(raw))

    def shutdown(self):
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=3)


def main():
    node = HostRodeCapture()
    if not node.start():
        return 1
    rospy.on_shutdown(node.shutdown)
    rospy.spin()
    return 0


if __name__ == "__main__":
    sys.exit(main())
