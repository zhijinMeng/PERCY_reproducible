#!/usr/bin/env python3
"""Post-process MP4 so container duration matches stamp-aligned audio (setpts, no frame drop)."""
from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys
import time


def _probe_duration(ffprobe, path):
    try:
        out = subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            stderr=subprocess.STDOUT,
            timeout=60,
        )
        return float(out.decode().strip())
    except (subprocess.CalledProcessError, OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _probe_codec(ffprobe, path):
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
                path,
            ],
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        return out.decode().strip()
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("meta_path", help="recording_meta.json path")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    args = parser.parse_args()

    meta_path = os.path.abspath(args.meta_path)
    out_dir = os.path.dirname(meta_path)
    done_path = os.path.join(out_dir, "finalize.done")
    log_path = os.path.join(out_dir, "finalize.log")

    with open(meta_path, "r") as f:
        meta = json.load(f)

    mp4 = meta.get("mp4")
    wav = meta.get("wav")
    frames = int(meta.get("frames") or 0)
    span = meta.get("video_stamp_span_sec")
    if span is None and meta.get("first_image_stamp") is not None and meta.get("last_image_stamp") is not None:
        span = float(meta["last_image_stamp"]) - float(meta["first_image_stamp"])

    if not mp4 or not os.path.isfile(mp4) or frames < 1:
        _fail(meta_path, meta, done_path, log_path, "missing mp4 or frames")
        return 1

    if span is None or float(span) <= 1e-3:
        _fail(meta_path, meta, done_path, log_path, "invalid stamp span")
        return 1

    fps = float(frames) / float(span)
    fps = max(0.25, min(fps, 120.0))

    do_h264 = bool(meta.get("video_transcode_h264", True))
    do_timeline = bool(meta.get("video_fix_timeline", True))
    preset = str(meta.get("video_finalize_preset") or "medium")
    if float(span) >= float(meta.get("video_finalize_ultrafast_sec", 120.0)):
        preset = "ultrafast"

    codec = _probe_codec(args.ffprobe, mp4)
    need_h264 = do_h264 and codec != "h264"
    need_timeline = do_timeline

    if not need_h264 and not need_timeline:
        _success(
            meta_path, meta, done_path, log_path, mp4, wav, fps, codec,
            args.ffprobe, skipped=True,
        )
        return 0

    tmp_path = mp4 + ".finalize.tmp.mp4"
    cmd = [args.ffmpeg, "-y", "-i", mp4]
    if need_timeline:
        cmd.extend(["-vf", "setpts=N/({:.6f}*TB)".format(fps)])
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            tmp_path,
        ]
    )

    timeout = max(
        int(meta.get("video_finalize_timeout_sec", 7200)),
        int(float(span) * 3) + 300,
    )

    with open(log_path, "a") as logf:
        logf.write(
            "finalize start span={:.2f}s frames={} fps={:.6f} preset={} timeout={}\n".format(
                span, frames, fps, preset, timeout
            )
        )
        logf.write("cmd: {}\n".format(" ".join(cmd)))
        logf.flush()
        t0 = time.time()
        try:
            subprocess.check_call(cmd, stdout=logf, stderr=subprocess.STDOUT, timeout=timeout)
            os.replace(tmp_path, mp4)
        except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as e:
            logf.write("finalize FAILED: {}\n".format(e))
            if os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            meta["finalize_status"] = "failed"
            meta["finalize_error"] = str(e)
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            return 1
        logf.write("finalize ffmpeg ok in {:.1f}s\n".format(time.time() - t0))

    final_codec = _probe_codec(args.ffprobe, mp4) or "h264"
    _success(
        meta_path, meta, done_path, log_path, mp4, wav, fps, final_codec,
        args.ffprobe, skipped=False,
    )
    return 0


def _success(meta_path, meta, done_path, log_path, mp4, wav, fps, codec, ffprobe, skipped):
    vd = _probe_duration(ffprobe, mp4)
    ad = _probe_duration(ffprobe, wav) if wav and os.path.isfile(wav) else None
    sync_err = None
    if vd is not None and ad is not None:
        sync_err = abs(vd - ad)

    meta["finalize_status"] = "ok" if not skipped else "skipped"
    meta["video_fps_corrected"] = fps
    meta["video_codec"] = codec
    meta["video_transcoded_h264"] = codec == "h264"
    meta["video_duration_sec"] = vd
    meta["audio_duration_sec"] = ad
    meta["av_sync_error_sec"] = sync_err
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    with open(done_path, "w") as f:
        f.write("ok\n")
    with open(log_path, "a") as f:
        f.write(
            "DONE video={:.3f}s audio={:.3f}s sync_err={}\n".format(
                vd or -1, ad or -1, sync_err
            )
        )
    print(
        "MP4 finalize done: {} (video {:.2f}s audio {:.2f}s err {})".format(
            mp4, vd or -1, ad or -1, sync_err
        ),
        flush=True,
    )


def _fail(meta_path, meta, done_path, log_path, msg):
    meta["finalize_status"] = "failed"
    meta["finalize_error"] = msg
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    with open(log_path, "a") as f:
        f.write("FAIL: {}\n".format(msg))


if __name__ == "__main__":
    sys.exit(main() or 0)
