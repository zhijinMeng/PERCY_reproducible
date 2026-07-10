"""Shared MERCI chat JSON loading and schema normalization (v1 + v2)."""
from __future__ import annotations

import json
from pathlib import Path

EMOTIONS = frozenset({"happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"})
SENTIMENTS = frozenset({"positive", "neutral", "negative"})

# Offline FER export order (PERCY mobilenet); matches Benchmark B feature columns.
FER_PROB_LABELS = ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise")

CHAT_CANDIDATES = (
    "chat_history_asr_aligned_large_v3.json",
    "chat_history_aligned.json",
    "chat_history.json",
)


def load_json_messages(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for key in ("messages", "turns", "dialogue_turns"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    if isinstance(data, list):
        return data
    return []


def visual_confidence(msg: dict) -> float | None:
    """Confidence for the visual emotion label (distribution mass or fused fallback)."""
    em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
    dist = msg.get("affect_fused_distribution")
    if isinstance(dist, dict) and em in dist:
        try:
            return float(dist[em])
        except (TypeError, ValueError):
            pass
    for key in ("emotion_visual_confidence", "visual_confidence", "affect_fused_confidence"):
        if msg.get(key) is not None:
            try:
                return float(msg[key])
            except (TypeError, ValueError):
                pass
    return None


def sentiment_confidence(msg: dict) -> float | None:
    if msg.get("sentiment_score") is None:
        return None
    try:
        return abs(float(msg["sentiment_score"]))
    except (TypeError, ValueError):
        return None


def normalize_message(msg: dict) -> dict:
    """Return a copy with legacy + v2 fields aligned."""
    out = dict(msg)
    em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
    if em in EMOTIONS:
        out["emotion"] = em
        out["emotion_visual"] = em
    sn = str(msg.get("sentiment", "")).lower().strip()
    if sn in SENTIMENTS:
        out["sentiment"] = sn
    if msg.get("t_start_sec") is not None and msg.get("asr_start") is None:
        out["asr_start"] = msg["t_start_sec"]
    if msg.get("t_end_sec") is not None and msg.get("asr_end") is None:
        out["asr_end"] = msg["t_end_sec"]
    if out.get("asr_start") is not None and "match_score" not in out:
        out["match_score"] = 100.0
        out["match_note"] = "live_timeline"
    vc = visual_confidence(msg)
    if vc is not None:
        out["emotion_visual_confidence"] = vc
    sc = sentiment_confidence(msg)
    if sc is not None:
        out["sentiment_confidence"] = sc
    return out


def normalize_messages(messages: list[dict]) -> list[dict]:
    return [normalize_message(m) for m in messages]


def fer_probs_from_message(msg: dict) -> dict[str, float] | None:
    """Read 7-dim FER probs from chat_history user turn (fer_probs dict or fer_p_* keys)."""
    raw = msg.get("fer_probs")
    if isinstance(raw, dict) and raw:
        out: dict[str, float] = {}
        for label in FER_PROB_LABELS:
            if label in raw:
                try:
                    out[label] = float(raw[label])
                except (TypeError, ValueError):
                    pass
        if out:
            s = sum(out.values())
            if s > 0:
                return {k: v / s for k, v in out.items()}
            return out
    flat: dict[str, float] = {}
    for label in FER_PROB_LABELS:
        key = f"fer_p_{label}"
        if msg.get(key) is not None:
            try:
                flat[label] = float(msg[key])
            except (TypeError, ValueError):
                pass
    if flat:
        s = sum(flat.values())
        if s > 0:
            return {k: v / s for k, v in flat.items()}
        return flat
    return None


def pick_chat_file(session_dir: Path) -> Path | None:
    for name in CHAT_CANDIDATES:
        p = session_dir / name
        if p.exists():
            return p
    return None


def canonical_messages(session_dir: Path) -> list[dict]:
    """Prefer dialogue_timeline.json; fall back to chat_history."""
    timeline = session_dir / "dialogue_timeline.json"
    if timeline.exists():
        return normalize_messages(load_json_messages(timeline))
    chat = pick_chat_file(session_dir)
    if chat:
        return normalize_messages(load_json_messages(chat))
    return []


def export_asr_aligned_v3(
    session_dir: Path,
    messages: list[dict],
    source_chat: Path,
) -> Path:
    out = session_dir / "chat_history_asr_aligned_large_v3.json"
    payload = {
        "source_chat": str(source_chat),
        "source_whisper": None,
        "whisper_model": "live_timeline",
        "alignment": "t_start_sec/t_end_sec mapped to asr_start/asr_end (no Whisper re-run)",
        "messages": normalize_messages(messages),
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
