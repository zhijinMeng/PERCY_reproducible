"""Discover MERCI session chat JSON under Research/percy_data."""
from __future__ import annotations

from pathlib import Path

from percy_data_root import FIXED_DATA_ARI, PERCY_DATA_ROOT

CHAT_PREFERENCE = (
    "chat_history_asr_aligned_large_v3.json",
    "chat_history_aligned.json",
    "chat_history.json",
)


def pick_chat_path(session_dir: Path) -> Path | None:
    for name in CHAT_PREFERENCE:
        p = session_dir / name
        if p.exists():
            return p
    return None


def iter_fixed_data_sessions() -> dict[str, Path]:
    """Timestamp-named sessions under fixed_data/Ari Robot."""
    seen: dict[str, Path] = {}
    if not FIXED_DATA_ARI.exists():
        return seen
    pending = FIXED_DATA_ARI / "_待处理"
    if pending.exists():
        for session_dir in sorted(pending.iterdir()):
            if session_dir.is_dir() and (chat_p := pick_chat_path(session_dir)):
                seen[session_dir.name] = chat_p
    # _人工修订 lives at Ari Robot/_人工修订 (not under _已处理).
    for bucket in ("_人工修订",):
        bucket_dir = FIXED_DATA_ARI / bucket
        if bucket_dir.exists():
            for session_dir in bucket_dir.iterdir():
                if session_dir.is_dir() and session_dir.name not in seen:
                    if chat_p := pick_chat_path(session_dir):
                        seen[session_dir.name] = chat_p
    processed = FIXED_DATA_ARI / "_已处理"
    for bucket in ("_含音轨mp4", "_无音轨mp4"):
        bucket_dir = processed / bucket
        if not bucket_dir.exists():
            continue
        for session_dir in bucket_dir.iterdir():
            if session_dir.is_dir() and session_dir.name not in seen:
                if chat_p := pick_chat_path(session_dir):
                    seen[session_dir.name] = chat_p
    return seen


def iter_numeric_sessions() -> dict[str, Path]:
    """Benchmark folders like percy_data/100 … percy_data/104."""
    seen: dict[str, Path] = {}
    if not PERCY_DATA_ROOT.exists():
        return seen
    for d in sorted(PERCY_DATA_ROOT.iterdir()):
        if d.is_dir() and d.name.isdigit() and (chat_p := pick_chat_path(d)):
            seen[d.name] = chat_p
    return seen


def iter_all_sessions(*, include_numeric: bool = True) -> list[tuple[str, Path]]:
    """All sessions for the full n=30 corpus (25 timestamp + 5 numeric)."""
    merged: dict[str, Path] = {}
    merged.update(iter_fixed_data_sessions())
    if include_numeric:
        for sid, path in iter_numeric_sessions().items():
            merged.setdefault(sid, path)
    return sorted(merged.items())
