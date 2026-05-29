#!/usr/bin/env python3
"""Normalize pending sessions (100-104): dedupe chat, export ASR-aligned JSON."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from merci_message_io import canonical_messages, export_asr_aligned_v3, load_json_messages

PENDING = Path(__file__).resolve().parents[3] / "fixed_data" / "Ari Robot" / "_待处理"
SESSION_IDS = ("100", "101", "102", "103", "104")
OUT_REPORT = Path(__file__).parent / "pending_sessions_fix_report.txt"


def fix_session(session_dir: Path) -> dict:
    sid = session_dir.name
    chat_path = session_dir / "chat_history.json"
    timeline_path = session_dir / "dialogue_timeline.json"

    old_chat_n = 0
    if chat_path.exists():
        old_chat_n = len(load_json_messages(chat_path))

    canonical = canonical_messages(session_dir)
    new_n = len(canonical)

    backup = session_dir / "chat_history.pre_fix.json"
    if chat_path.exists() and not backup.exists():
        shutil.copy2(chat_path, backup)

    chat_path.write_text(
        json.dumps(canonical, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    source = timeline_path if timeline_path.exists() else chat_path
    v3_path = export_asr_aligned_v3(session_dir, canonical, source)

    # Stub whisper file pointer for benchmark_manifest compatibility
    whisper_stub = session_dir / "audio_whisper_large-v3.json"
    if not whisper_stub.exists():
        whisper_stub.write_text(
            json.dumps(
                {
                    "model": "live_timeline",
                    "note": "ASR boundaries taken from per-turn t_start_sec/t_end_sec; Whisper not re-run.",
                    "segments": [],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    manifest_path = session_dir / "benchmark_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = manifest.setdefault("files", {})
        files["chat_history"] = str(chat_path)
        files["whisper_asr"] = str(whisper_stub)
        manifest["dialogue_turns"] = new_n
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "session_id": sid,
        "old_chat_messages": old_chat_n,
        "canonical_messages": new_n,
        "removed_duplicates": max(0, old_chat_n - new_n),
        "used_timeline": timeline_path.exists(),
        "wrote_v3": str(v3_path.name),
    }


def main() -> None:
    lines = ["Pending session fix report", "=" * 50]
    for sid in SESSION_IDS:
        d = PENDING / sid
        if not d.is_dir():
            lines.append(f"{sid}: MISSING")
            continue
        r = fix_session(d)
        lines.append(
            f"{r['session_id']}: chat {r['old_chat_messages']} -> {r['canonical_messages']} "
            f"(removed {r['removed_duplicates']}, timeline={r['used_timeline']}) "
            f"+ {r['wrote_v3']}"
        )

    text = "\n".join(lines) + "\n"
    OUT_REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote {OUT_REPORT}")


if __name__ == "__main__":
    main()
