#!/usr/bin/env python3
"""5s direct capture test (bypass ROS). Compare ffmpeg vs arecord."""
from __future__ import print_function

import argparse
import math
import os
import struct
import subprocess
import sys
import wave

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from host_usb_mic_detect import detect_host_usb_mic  # noqa: E402


def analyze_wav(path):
    with wave.open(path, "rb") as w:
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    s = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    rms = math.sqrt(sum(x * x for x in s) / max(len(s), 1))
    peak = max(abs(x) for x in s) if s else 0
    clip = sum(1 for x in s if abs(x) >= 30000) / max(len(s), 1)
    db = 20 * math.log10(max(rms, 1) / 32768.0)
    return {"sr": sr, "dbfs": db, "peak": peak, "clip_pct": clip * 100}


def capture_ffmpeg(device, out_path, sec, rate=16000):
    subprocess.check_call(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "alsa",
            "-i",
            device,
            "-t",
            str(sec),
            "-ac",
            "1",
            "-ar",
            str(rate),
            out_path,
        ]
    )


def capture_arecord(device, out_path, sec, rate=48000, ch=2):
    subprocess.check_call(
        [
            "arecord",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-r",
            str(rate),
            "-c",
            str(ch),
            "-d",
            str(sec),
            out_path,
        ]
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="auto")
    ap.add_argument("--sec", type=float, default=5.0)
    ap.add_argument("--out-dir", default="/tmp/rode_sanity")
    args = ap.parse_args()
    dev = args.device
    if dev in ("", "auto"):
        dev = detect_host_usb_mic() or ""
    if not dev:
        print("No USB mic", file=sys.stderr)
        return 1
    os.makedirs(args.out_dir, exist_ok=True)
    print("device:", dev)
    print("Speak into the mic during capture.\n")
    ff = os.path.join(args.out_dir, "ffmpeg_16k.wav")
    ar = os.path.join(args.out_dir, "arecord_48k_stereo.wav")
    capture_ffmpeg(dev, ff, args.sec)
    capture_arecord(dev, ar, args.sec)
    a = analyze_wav(ff)
    b = analyze_wav(ar)
    print("ffmpeg 16k mono:", a)
    print("arecord 48k stereo:", b)
    print("Listen:", ff, ar)
    if a["dbfs"] > -12 and a["clip_pct"] > 1:
        print("WARN: ffmpeg path still very hot / clipped")
    if b["dbfs"] > -12:
        print("WARN: arecord path very hot — likely format/gain issue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
