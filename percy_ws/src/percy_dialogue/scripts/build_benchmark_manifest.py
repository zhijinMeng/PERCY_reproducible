#!/usr/bin/env python3
"""
Build benchmark_manifest.json for a session (post-recording).

Merges:
  recording_meta.json
  dialogue_timeline.json  (or chat_history.json with t_* fields)
  optional audio_whisper_large_v3.json

Usage:
  rosrun percy_dialogue build_benchmark_manifest.py /path/to/percy_data/13
"""
from __future__ import print_function

import argparse
import json
import os
import sys


def _load(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir")
    args = parser.parse_args()
    session_dir = os.path.abspath(args.session_dir)
    session_id = os.path.basename(session_dir)

    meta = _load(os.path.join(session_dir, "recording_meta.json"))
    if meta is None:
        print("missing recording_meta.json", file=sys.stderr)
        return 1

    timeline = _load(os.path.join(session_dir, "dialogue_timeline.json"))
    chat = _load(os.path.join(session_dir, "chat_history.json"))
    whisper = _load(os.path.join(session_dir, "audio_whisper_large_v3.json"))

    turns = []
    if timeline and timeline.get("turns"):
        turns = timeline["turns"]
    elif chat and isinstance(chat, list):
        turns = chat

    utterances_dir_path = os.path.join(session_dir, "utterances")
    utterance_wavs = []
    if os.path.isdir(utterances_dir_path):
        utterance_wavs = sorted(
            os.path.join(utterances_dir_path, name)
            for name in os.listdir(utterances_dir_path)
            if name.endswith(".wav")
        )
    else:
        utterance_wavs = sorted(
            os.path.join(session_dir, name)
            for name in os.listdir(session_dir)
            if name.startswith("utterance_") and name.endswith(".wav")
        )

    manifest = {
        "session_id": meta.get("session_id", session_id),
        "benchmark_version": "1.0",
        "timeline": {
            "origin_ros_sec": meta.get("first_image_stamp"),
            "span_sec": meta.get("video_stamp_span_sec") or meta.get("video_duration_sec"),
            "note": "Use t_start_sec/t_end_sec to cut audio.wav or whole_video.mp4 (t=0 at origin).",
        },
        "files": {
            "audio_wav": meta.get("wav"),
            "video_mp4": meta.get("mp4"),
            "recording_meta": os.path.join(session_dir, "recording_meta.json"),
            "dialogue_timeline": os.path.join(session_dir, "dialogue_timeline.json"),
            "chat_history": os.path.join(session_dir, "chat_history.json"),
            "utterances_dir": utterances_dir_path
            if os.path.isdir(utterances_dir_path)
            else None,
            "whisper_asr": os.path.join(session_dir, "audio_whisper_large_v3.json")
            if whisper
            else None,
        },
        "utterance_wavs": utterance_wavs,
        "recording": meta,
        "dialogue_turns": turns,
        "whisper_segment_count": len(whisper.get("segments", [])) if whisper else 0,
    }

    out_path = os.path.join(session_dir, "benchmark_manifest.json")
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print("Wrote {} ({} dialogue turns)".format(out_path, len(turns)))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
