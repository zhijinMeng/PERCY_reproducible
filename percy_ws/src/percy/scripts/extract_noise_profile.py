#!/usr/bin/env python3
"""
从长 audio.wav 自动找出「安静 / 风扇(高噪)」区段，导出噪声谱 profile。

用法:
  rosrun percy extract_noise_profile.py /workspace/percy_data/noise_floor03
  rosrun percy extract_noise_profile.py /path/to/audio.wav --out-dir /tmp/out

输出（在 session 目录或 --out-dir）:
  noise_profile_report.json   — 区段列表与统计
  noise_profile_quiet.json    — 安静段平均谱（供 turn_dialogue 加载）
  noise_profile_fan.json      — 高噪段平均谱（若存在）
  noise_quiet_clip.wav        — 最长安静段剪辑（可选对照听）
  noise_fan_clip.wav          — 最长高噪段剪辑
"""
from __future__ import division, print_function

import argparse
import json
import math
import os
import sys
import wave

import numpy as np

# 与 turn_dialogue 共用谱估计逻辑
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DIALOGUE_SCRIPTS = os.path.normpath(
    os.path.join(_SCRIPT_DIR, "..", "..", "percy_dialogue", "scripts")
)
if _DIALOGUE_SCRIPTS not in sys.path:
    sys.path.insert(0, _DIALOGUE_SCRIPTS)

from audio_preprocess import estimate_noise_magnitude, save_noise_profile  # noqa: E402


def read_wav(path):
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        if sw != 2:
            raise ValueError("only 16-bit PCM supported")
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        samples = samples.reshape(-1, ch)[:, 0]
    return sr, samples


def write_wav(path, sr, samples):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples.astype(np.int16).tobytes())


def rms_dbfs(segment):
    if len(segment) == 0:
        return -120.0
    rms = math.sqrt(float(np.mean(segment.astype(np.float64) ** 2)))
    return 20.0 * math.log10(rms / 32768.0 + 1e-12)


def window_dbfs(samples, sr, window_sec):
    win = int(sr * window_sec)
    out = []
    for i in range(0, len(samples) - win + 1, win):
        out.append(rms_dbfs(samples[i : i + win]))
    if not out and len(samples) > 0:
        out.append(rms_dbfs(samples))
    return out


def find_runs(labels):
    """labels: list of str 'quiet'|'loud'|'mid' -> [(kind, start_idx, end_idx)]."""
    runs = []
    if not labels:
        return runs
    cur = labels[0]
    start = 0
    for i in range(1, len(labels)):
        if labels[i] != cur:
            if cur in ("quiet", "loud"):
                runs.append((cur, start, i))
            cur = labels[i]
            start = i
    if cur in ("quiet", "loud"):
        runs.append((cur, start, len(labels)))
    return runs


def pick_longest_run(runs, kind):
    cand = [(e - s, s, e) for k, s, e in runs if k == kind]
    if not cand:
        return None
    cand.sort(reverse=True)
    _, s, e = cand[0]
    return s, e


def main():
    ap = argparse.ArgumentParser(description="Extract quiet/fan noise profiles from wav")
    ap.add_argument(
        "input",
        help="audio.wav 或 session 目录（含 audio.wav）",
    )
    ap.add_argument("--out-dir", default="", help="输出目录（默认=input 若为目录，否则 wav 同目录）")
    ap.add_argument("--window-sec", type=float, default=1.0)
    ap.add_argument("--quiet-db", type=float, default=-35.0, help="RMS 低于此为安静")
    ap.add_argument("--loud-db", type=float, default=-15.0, help="RMS 高于此为高噪(风扇)")
    ap.add_argument("--min-run-sec", type=float, default=3.0, help="最短区段才导出 profile")
    ap.add_argument("--max-clip-sec", type=float, default=30.0, help="剪辑 wav 最长秒数")
    ap.add_argument("--highpass-hz", type=float, default=80.0)
    args = ap.parse_args()

    inp = os.path.abspath(args.input)
    if os.path.isdir(inp):
        wav_path = os.path.join(inp, "audio.wav")
        out_dir = args.out_dir or inp
    else:
        wav_path = inp
        out_dir = args.out_dir or os.path.dirname(wav_path)
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.isfile(wav_path):
        print("ERROR: not found:", wav_path, file=sys.stderr)
        return 1

    sr, samples = read_wav(wav_path)
    dur = len(samples) / float(sr)
    db_series = window_dbfs(samples, sr, args.window_sec)
    nwin = len(db_series)

    labels = []
    for db in db_series:
        if db < args.quiet_db:
            labels.append("quiet")
        elif db > args.loud_db:
            labels.append("loud")
        else:
            labels.append("mid")

    runs = find_runs(labels)
    min_windows = max(1, int(math.ceil(args.min_run_sec / args.window_sec)))

    report = {
        "source_wav": wav_path,
        "duration_sec": dur,
        "sample_rate": sr,
        "window_sec": args.window_sec,
        "quiet_db_threshold": args.quiet_db,
        "loud_db_threshold": args.loud_db,
        "per_window_dbfs": [round(x, 2) for x in db_series],
        "labels": labels,
        "segments": [],
    }

    for kind, s, e in runs:
        seg_len = e - s
        t0 = s * args.window_sec
        t1 = min(dur, e * args.window_sec)
        report["segments"].append(
            {
                "kind": kind,
                "t_start_sec": round(t0, 3),
                "t_end_sec": round(t1, 3),
                "duration_sec": round(t1 - t0, 3),
                "mean_dbfs": round(float(np.mean(db_series[s:e])), 2),
                "usable_for_profile": seg_len >= min_windows,
            }
        )

    report_path = os.path.join(out_dir, "noise_profile_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("=== %s ===" % wav_path)
    print("duration=%.1fs windows=%d (%.1fs)" % (dur, nwin, args.window_sec))
    print("thresholds: quiet < %.1f dBFS , loud > %.1f dBFS" % (args.quiet_db, args.loud_db))
    print("segments:")
    for seg in report["segments"]:
        flag = "OK" if seg["usable_for_profile"] else "skip"
        print(
            "  [%s] %s %.1f-%.1fs mean=%.1f dBFS (%s)"
            % (flag, seg["kind"], seg["t_start_sec"], seg["t_end_sec"], seg["mean_dbfs"], seg["duration_sec"])
        )

    def export_kind(kind, json_name, clip_name):
        sel = pick_longest_run(
            [(k, s, e) for k, s, e in runs if k == kind and (e - s) >= min_windows],
            kind,
        )
        if not sel:
            print("no usable %s segment (>=%.1fs)" % (kind, args.min_run_sec))
            return None
        s, e = sel
        i0 = int(s * args.window_sec * sr)
        i1 = int(min(len(samples), e * args.window_sec * sr))
        clip = samples[i0:i1]
        if len(clip) < sr:
            print("%s segment too short for spectrum" % kind)
            return None
        mag = estimate_noise_magnitude(clip, sample_rate=sr, highpass_hz=args.highpass_hz)
        if mag is None:
            print("failed to estimate spectrum for", kind)
            return None
        meta = {
            "kind": kind,
            "t_start_sec": s * args.window_sec,
            "t_end_sec": i1 / float(sr),
            "source_wav": wav_path,
            "highpass_hz": args.highpass_hz,
        }
        out_json = os.path.join(out_dir, json_name)
        save_noise_profile(out_json, mag, meta)
        max_clip = int(args.max_clip_sec * sr)
        clip_path = os.path.join(out_dir, clip_name)
        write_wav(clip_path, sr, clip[:max_clip])
        print("wrote %s and %s (%.1fs clip)" % (out_json, clip_path, min(len(clip), max_clip) / float(sr)))
        return out_json

    export_kind("quiet", "noise_profile_quiet.json", "noise_quiet_clip.wav")
    export_kind("loud", "noise_profile_fan.json", "noise_fan_clip.wav")

    print("report:", report_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
