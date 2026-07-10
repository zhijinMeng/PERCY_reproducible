"""Load MERCI sessions from HF_Data/percy_data/normalized_media (30 non-quarantine)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from merci_message_io import canonical_messages, normalize_messages

_ANALYSIS = Path(__file__).resolve().parent
_CANDIDATES = [
    _ANALYSIS.parent / "data" / "normalized_media",
    _ANALYSIS.parents[3] / "HF_Data" / "percy_data" / "normalized_media",
    _ANALYSIS.parents[4] / "HF_Data" / "percy_data" / "normalized_media",
]
_DEFAULT = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

NORMALIZED_MEDIA_ROOT = Path(
    os.environ.get("NORMALIZED_MEDIA_ROOT", _DEFAULT)
).resolve()


def iter_normalized_sessions(*, exclude_quarantine: bool = True) -> list[tuple[str, Path]]:
    if not NORMALIZED_MEDIA_ROOT.exists():
        return []
    out: list[tuple[str, Path]] = []
    for d in sorted(NORMALIZED_MEDIA_ROOT.iterdir()):
        if not d.is_dir():
            continue
        if exclude_quarantine and d.name.startswith("_"):
            continue
        if (d / "chat_history.json").exists() or (d / "dialogue_timeline.json").exists():
            out.append((d.name, d))
    return out


def load_session_messages(session_dir: Path) -> list[dict]:
    return canonical_messages(session_dir)


def load_normalize_report() -> dict:
    report_path = NORMALIZED_MEDIA_ROOT / "normalize_report.json"
    if report_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8"))
    return {}
