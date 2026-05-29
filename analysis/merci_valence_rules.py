"""Paper §3.2 valence-level turn classes (deployed MERCI audit rule)."""
from __future__ import annotations

EMOTIONS = frozenset({"happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"})
SENTIMENTS = frozenset({"positive", "neutral", "negative"})
VISUAL_POSITIVE = frozenset({"happy"})
VISUAL_NEGATIVE = frozenset({"sad", "angry", "disgust", "fear"})


def classify_turn(emotion: str, sentiment: str) -> str:
    """One of consistent | neutral | conflict | other (paper §3.2)."""
    emotion = (emotion or "").strip().lower()
    sentiment = (sentiment or "").strip().lower()
    if emotion == "neutral" or sentiment == "neutral":
        return "neutral"
    if emotion in VISUAL_POSITIVE and sentiment == "positive":
        return "consistent"
    if emotion in VISUAL_NEGATIVE and sentiment == "negative":
        return "consistent"
    if emotion in VISUAL_POSITIVE and sentiment == "negative":
        return "conflict"
    if emotion in VISUAL_NEGATIVE and sentiment == "positive":
        return "conflict"
    return "other"


def valence_conflict(visual: str, sentiment: str) -> bool:
    """Deployed valence-conflict flag (same as classify_turn == conflict)."""
    return classify_turn(visual, sentiment) == "conflict"
