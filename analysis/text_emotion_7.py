"""Seven-class text emotion for MERCI cross-modal analysis.

Channels
--------
* **vader7** (Plan A): ``sentiment`` field -> ``_SENTIMENT_TO_DIST`` (same as live PERCY).
* **lexicon**: lightweight offline English lexicon scorer (stdlib only).
* **hf** (optional): ``j-hartmann/emotion-english-distilroberta-base`` when torch/transformers installed.

Run batch labelling::

    python text_emotion_7.py --channels vader7,lexicon
    python text_emotion_7.py --channels vader7,lexicon,hf   # after pip install -r requirements-analysis.txt
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

# Repo-root percy_affect (VADER 7-expansion)
_REPO_SCRIPTS = Path(__file__).resolve().parents[4] / "percy_ws" / "src" / "percy_dialogue" / "scripts"
if _REPO_SCRIPTS.is_dir() and str(_REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_REPO_SCRIPTS))

from percy_affect import VALID_EMOTIONS, text_emotion_7_from_sentiment  # noqa: E402

from cross_modal_consistency import load_chat_history  # noqa: E402
from merci_session_discovery import iter_all_sessions  # noqa: E402

OUT_DIR = Path(__file__).parent
OUT_CSV = OUT_DIR / "text_emotion_7_labels.csv"

# Minimal Ekman-style lexicon (offline baseline; not neural).
_LEXICON: dict[str, tuple[str, ...]] = {
    "happy": (
        "happy", "glad", "joy", "love", "wonderful", "great", "excited", "fun",
        "enjoy", "awesome", "fantastic", "amazing", "good", "nice", "thank",
    ),
    "sad": (
        "sad", "unhappy", "depressed", "lonely", "cry", "miss", "sorry", "upset",
        "disappointed", "grief", "hurt",
    ),
    "angry": (
        "angry", "mad", "furious", "annoyed", "hate", "frustrated", "rage",
        "irritated",
    ),
    "disgust": ("disgust", "gross", "nasty", "awful", "terrible", "hate"),
    "fear": ("afraid", "fear", "scared", "worry", "anxious", "nervous", "stress"),
    "surprise": ("wow", "surprise", "unexpected", "shocked", "amazing"),
    "neutral": ("okay", "fine", "maybe", "think", "guess"),
}

_HF_LABEL_MAP = {
    "anger": "angry",
    "joy": "happy",
    "sadness": "sad",
    "fear": "fear",
    "disgust": "disgust",
    "surprise": "surprise",
    "neutral": "neutral",
}

_TOKEN_RE = re.compile(r"[a-z']+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def text_emotion_7_lexicon(text: str, compound: float | None = None) -> tuple[str, dict[str, float]]:
    """Score 7 classes from word hits; optional VADER compound prior."""
    scores = {k: 0.1 for k in VALID_EMOTIONS}
    for tok in _tokenize(text):
        for emo, words in _LEXICON.items():
            if tok in words:
                scores[emo] += 1.0
    if compound is not None:
        if compound > 0.05:
            scores["happy"] += 1.5
            scores["surprise"] += 0.3
        elif compound < -0.05:
            scores["sad"] += 1.0
            scores["angry"] += 0.6
            scores["disgust"] += 0.4
        else:
            scores["neutral"] += 1.0
    total = sum(scores.values()) or 1.0
    dist = {k: scores[k] / total for k in VALID_EMOTIONS}
    label = max(dist, key=dist.get)
    return label, dist


_hf_pipeline = None


def text_emotion_7_hf(text: str) -> tuple[str, dict[str, float]]:
    """HuggingFace 7-class English emotion (requires transformers + torch)."""
    global _hf_pipeline
    if _hf_pipeline is None:
        from transformers import pipeline

        _hf_pipeline = pipeline(
            "text-classification",
            model="j-hartmann/emotion-english-distilroberta-base",
            top_k=None,
            device=-1,
        )
    preds = _hf_pipeline((text or "")[:512])[0]
    dist = {k: 0.0 for k in VALID_EMOTIONS}
    for item in preds:
        raw = item["label"].lower()
        emo = _HF_LABEL_MAP.get(raw, raw)
        if emo in dist:
            dist[emo] += float(item["score"])
    total = sum(dist.values()) or 1.0
    dist = {k: dist[k] / total for k in VALID_EMOTIONS}
    label = max(dist, key=dist.get)
    return label, dist


def label_turn(
    msg: dict,
    channels: set[str],
) -> dict:
    vis = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
    sn = str(msg.get("sentiment", "")).lower().strip()
    text = str(msg.get("content", "") or "")
    compound = msg.get("sentiment_score")
    try:
        compound_f = float(compound) if compound is not None else None
    except (TypeError, ValueError):
        compound_f = None

    row = {
        "visual_emotion_7": vis if vis in VALID_EMOTIONS else "",
        "sentiment_3": sn,
        "sentiment_score": compound_f if compound_f is not None else "",
    }
    if "vader7" in channels and sn in ("positive", "neutral", "negative"):
        t7, _ = text_emotion_7_from_sentiment(sn)
        row["text7_vader7"] = t7
    if "lexicon" in channels:
        row["text7_lexicon"], _ = text_emotion_7_lexicon(text, compound_f)
    if "hf" in channels:
        try:
            row["text7_hf"], _ = text_emotion_7_hf(text)
        except ImportError as e:
            raise SystemExit(
                "HF channel requires: pip install -r requirements-analysis.txt\n"
                f"Import error: {e}"
            ) from e
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--channels",
        default="vader7,lexicon",
        help="Comma-separated: vader7, lexicon, hf",
    )
    args = ap.parse_args()
    channels = {c.strip() for c in args.channels.split(",") if c.strip()}

    rows: list[dict] = []
    for sid, path in iter_all_sessions():
        for i, msg in enumerate(load_chat_history(path)):
            if msg.get("role") != "user":
                continue
            vis = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            sn = str(msg.get("sentiment", "")).lower().strip()
            if vis not in VALID_EMOTIONS:
                continue
            base = {
                "session_id": sid,
                "turn_index": i,
                "content_preview": str(msg.get("content", ""))[:100],
            }
            base.update(label_turn(msg, channels))
            rows.append(base)

    if not rows:
        print("No rows labelled.")
        return

    fieldnames = list(rows[0].keys())
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {OUT_CSV} ({len(rows)} user turns, channels={channels})")

    for ch_col in [c for c in fieldnames if c.startswith("text7_")]:
        agree = sum(
            1 for r in rows
            if r.get("visual_emotion_7") and r.get(ch_col)
            and r["visual_emotion_7"] == r[ch_col]
        )
        n = sum(1 for r in rows if r.get(ch_col))
        both_nn = sum(
            1 for r in rows
            if r.get("visual_emotion_7") not in ("", "neutral")
            and r.get(ch_col) not in ("", "neutral")
            and r["visual_emotion_7"] != r[ch_col]
        )
        print(f"  {ch_col}: exact match {agree}/{n} ({100*agree/max(n,1):.1f}%), "
              f"both-non-neutral mismatch {both_nn}/{n} ({100*both_nn/max(n,1):.1f}%)")


if __name__ == "__main__":
    main()
