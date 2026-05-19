#!/usr/bin/env python3
"""
Offline Whisper ASR on stamp-aligned session audio; export MERCI-style timeline JSON.

Timeline: seconds from session start = start of audio.wav (= first_image_stamp in meta).

Outputs (in session dir):
  audio_whisper_large_v3.json       — raw segments + word timestamps
  chat_history_asr_aligned_large_v3.json — turn rows for benchmark / gap analysis

Requires one of:
  - faster-whisper (pip install faster-whisper)
  - openai-whisper CLI: whisper audio.wav --model large-v3 --output_format json

Usage:
  python3 benchmark_whisper_align.py /path/to/percy_data/10
  python3 benchmark_whisper_align.py /path/to/percy_data/10 --model large-v2
"""
from __future__ import print_function

import argparse
import json
import os
import subprocess
import sys
import tempfile


def _load_meta(session_dir):
    meta_path = os.path.join(session_dir, "recording_meta.json")
    if not os.path.isfile(meta_path):
        raise SystemExit("missing recording_meta.json in {}".format(session_dir))
    with open(meta_path, "r") as f:
        return json.load(f)


def _transcribe_faster_whisper(wav_path, model_name, device, compute_type):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        wav_path,
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
    )
    segments = []
    for seg in segments_iter:
        words = []
        if seg.words:
            for w in seg.words:
                words.append(
                    {
                        "word": w.word,
                        "start": float(w.start),
                        "end": float(w.end),
                    }
                )
        segments.append(
            {
                "id": len(segments),
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
                "words": words,
            }
        )
    return {
        "backend": "faster-whisper",
        "language": info.language,
        "duration_sec": float(info.duration),
        "segments": segments,
    }


def _transcribe_whisper_cli(wav_path, model_name):
    if not _which("whisper"):
        return None
    out_dir = tempfile.mkdtemp(prefix="whisper_out_")
    cmd = [
        "whisper",
        wav_path,
        "--model",
        model_name,
        "--output_format",
        "json",
        "--output_dir",
        out_dir,
        "--word_timestamps",
        "True",
    ]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    except (subprocess.CalledProcessError, OSError) as e:
        raise SystemExit("whisper CLI failed: {}".format(e))

    base = os.path.splitext(os.path.basename(wav_path))[0]
    json_path = os.path.join(out_dir, base + ".json")
    if not os.path.isfile(json_path):
        raise SystemExit("whisper CLI did not produce {}".format(json_path))
    with open(json_path, "r") as f:
        raw = json.load(f)

    segments = []
    for i, seg in enumerate(raw.get("segments", [])):
        segments.append(
            {
                "id": i,
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": str(seg.get("text", "")).strip(),
                "words": [
                    {
                        "word": w.get("word", ""),
                        "start": float(w["start"]),
                        "end": float(w["end"]),
                    }
                    for w in seg.get("words", []) or []
                ],
            }
        )
    return {
        "backend": "openai-whisper-cli",
        "language": raw.get("language"),
        "duration_sec": segments[-1]["end"] if segments else 0.0,
        "segments": segments,
    }


def _which(cmd):
    from shutil import which

    return which(cmd)


def _build_turn_rows(segments, role="unknown"):
    """One row per Whisper segment; role must be filled later (e.g. merge with PERCY chat)."""
    rows = []
    for seg in segments:
        rows.append(
            {
                "role": role,
                "content": seg["text"],
                "asr_start": seg["start"],
                "asr_end": seg["end"],
                "segment_id": seg["id"],
            }
        )
    return rows


def main():
    parser = argparse.ArgumentParser(description="Whisper ASR export for benchmark sessions")
    parser.add_argument("session_dir", help="e.g. /workspace/percy_data/10")
    parser.add_argument("--model", default="large-v3", help="large-v2 or large-v3")
    parser.add_argument("--device", default="cuda", help="cuda or cpu (faster-whisper)")
    parser.add_argument("--compute-type", default="float16", help="float16/int8_float16/cpu")
    args = parser.parse_args()

    session_dir = os.path.abspath(args.session_dir)
    wav_path = os.path.join(session_dir, "audio.wav")
    if not os.path.isfile(wav_path):
        raise SystemExit("missing audio.wav in {}".format(session_dir))

    meta = _load_meta(session_dir)
    origin = meta.get("first_image_stamp")
    span = meta.get("video_stamp_span_sec")
    if span is None and origin is not None and meta.get("last_image_stamp") is not None:
        span = float(meta["last_image_stamp"]) - float(origin)

    result = _transcribe_faster_whisper(
        wav_path, args.model, args.device, args.compute_type
    )
    if result is None:
        print("faster-whisper not available, trying whisper CLI...", file=sys.stderr)
        result = _transcribe_whisper_cli(wav_path, args.model)
    if result is None:
        raise SystemExit(
            "Install faster-whisper (pip install faster-whisper) or openai-whisper CLI"
        )

    audio_json = {
        "session_id": meta.get("session_id", os.path.basename(session_dir)),
        "wav": wav_path,
        "mp4": meta.get("mp4"),
        "whisper_model": args.model,
        "whisper_backend": result["backend"],
        "language": result.get("language"),
        "timeline": {
            "origin_ros_sec": origin,
            "span_sec": span,
            "note": "asr_start/asr_end are seconds from start of audio.wav (aligned record)",
        },
        "segments": result["segments"],
    }
    audio_out = os.path.join(session_dir, "audio_whisper_large_v3.json")
    with open(audio_out, "w") as f:
        json.dump(audio_json, f, indent=2, ensure_ascii=False)

    chat_out = os.path.join(session_dir, "chat_history_asr_aligned_large_v3.json")
    chat_doc = {
        "session_id": audio_json["session_id"],
        "whisper_model": args.model,
        "timeline": audio_json["timeline"],
        "turns": _build_turn_rows(result["segments"]),
        "note": (
            "Each row is one Whisper segment on the session timeline. "
            "Assign role=user|assistant by merging with PERCY chat_history.json "
            "or diarization; use for benchmark ASR and inter-turn gap (Section 4.1)."
        ),
    }
    with open(chat_out, "w") as f:
        json.dump(chat_doc, f, indent=2, ensure_ascii=False)

    print("Wrote {} ({} segments)".format(audio_out, len(result["segments"])))
    print("Wrote {}".format(chat_out))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
