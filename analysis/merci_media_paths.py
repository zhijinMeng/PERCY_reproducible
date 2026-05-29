"""Resolve session video paths for human-conflict annotation clips."""
from __future__ import annotations

from pathlib import Path


def session_dir_from_chat(chat_path: Path) -> Path:
    return chat_path.parent


def pick_video(session_dir: Path) -> Path | None:
    """Prefer whole_video (numeric release), then any mp4 in session folder."""
    for name in ("whole_video.mp4", "side_video.mp4"):
        p = session_dir / name
        if p.is_file():
            return p.resolve()
    mp4s = sorted(session_dir.glob("*.mp4"), key=lambda p: p.stat().st_size, reverse=True)
    return mp4s[0].resolve() if mp4s else None


def clip_window(t_start: float | None, t_end: float | None, *, pad: float = 1.0) -> tuple[float, float] | None:
    if t_start is None:
        return None
    start = max(0.0, float(t_start) - pad)
    if t_end is not None:
        end = float(t_end) + pad
        if end <= start:
            end = start + 3.0
    else:
        end = start + 5.0
    return start, end
