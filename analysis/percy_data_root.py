"""Canonical MERCI data root for analysis scripts."""
from __future__ import annotations

import os
from pathlib import Path

_ANALYSIS = Path(__file__).resolve().parent
_CANDIDATES = [
    _ANALYSIS.parent / "data" / "percy_data",
    _ANALYSIS.parents[4] / "percy_data",
    _ANALYSIS.parents[4] / "HF_Data" / "percy_data",
]
_DEFAULT = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])

PERCY_DATA_ROOT = Path(os.environ.get("PERCY_DATA_ROOT", _DEFAULT)).resolve()

FIXED_DATA_ARI = PERCY_DATA_ROOT / "fixed_data" / "Ari Robot"
