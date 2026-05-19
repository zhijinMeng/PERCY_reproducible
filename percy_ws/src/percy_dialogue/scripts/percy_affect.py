#!/usr/bin/env python3
"""
MERCI / journal-aligned affect helpers: VADER sentiment + optional visual FER fusion.

Paper defaults: w_visual=0.6, w_text=0.4; VADER polarity thresholds ±0.05 on compound.
"""

from __future__ import print_function

import threading

VALID_EMOTIONS = ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise")

# Map VADER 3-class polarity to a soft 7-class distribution (text channel).
_SENTIMENT_TO_DIST = {
    "positive": {"happy": 0.72, "surprise": 0.18, "neutral": 0.10},
    "negative": {"sad": 0.45, "angry": 0.30, "disgust": 0.15, "fear": 0.10},
    "neutral": {"neutral": 1.0},
}


def _normalize_dist(dist):
    total = sum(dist.values())
    if total <= 0:
        return {k: 0.0 for k in VALID_EMOTIONS}
    return {k: dist.get(k, 0.0) / total for k in VALID_EMOTIONS}


def _one_hot(label):
    dist = {k: 0.0 for k in VALID_EMOTIONS}
    label = (label or "neutral").strip().lower()
    if label in VALID_EMOTIONS:
        dist[label] = 1.0
    else:
        dist["neutral"] = 1.0
    return dist


def parse_visual_emotion_msg(raw):
    """Parse emotiondetect_result ('happy' or 'happy, sad')."""
    if not raw:
        return "neutral"
    for part in str(raw).split(","):
        emo = part.strip().lower()
        if emo in VALID_EMOTIONS:
            return emo
    return "neutral"


def vader_sentiment(analyzer, text):
    """
    Returns (polarity_label, compound_score).
    polarity in {positive, neutral, negative}; compound in [-1, 1].
    """
    scores = analyzer.polarity_scores(text or "")
    compound = float(scores.get("compound", 0.0))
    if compound < -0.05:
        label = "negative"
    elif compound > 0.05:
        label = "positive"
    else:
        label = "neutral"
    return label, compound


def fuse_emotion_distributions(p_vis, p_txt, w_vis=0.6, w_txt=0.4):
    fused = {k: w_vis * p_vis.get(k, 0.0) + w_txt * p_txt.get(k, 0.0) for k in VALID_EMOTIONS}
    fused = _normalize_dist(fused)
    label = max(fused, key=fused.get)
    confidence = fused[label]
    return label, confidence, fused


def analyze_user_affect(
    analyzer,
    transcript,
    visual_emotion=None,
    w_vis=0.6,
    w_txt=0.4,
):
    """
    Full turn-level affect record for chat_history / cross-modal analysis.

    visual_emotion: latest FER label or None -> treated as neutral one-hot.
    """
    sentiment, compound = vader_sentiment(analyzer, transcript)
    p_txt = _normalize_dist(dict(_SENTIMENT_TO_DIST[sentiment]))
    vis_label = parse_visual_emotion_msg(visual_emotion) if visual_emotion else "neutral"
    p_vis = _one_hot(vis_label)
    fused_label, fused_conf, fused_dist = fuse_emotion_distributions(
        p_vis, p_txt, w_vis=w_vis, w_txt=w_txt
    )
    return {
        "emotion_visual": vis_label,
        "sentiment": sentiment,
        "sentiment_score": round(compound, 4),
        "affect_fused": fused_label,
        "affect_fused_confidence": round(fused_conf, 4),
        "affect_fusion_weights": {"visual": w_vis, "text": w_txt},
        "affect_fused_distribution": {k: round(fused_dist[k], 4) for k in VALID_EMOTIONS},
    }


def empathy_system_note(affect_fields):
    """Short English note for GPT system injection (MERCI-style)."""
    vis = affect_fields.get("emotion_visual", "neutral")
    sent = affect_fields.get("sentiment", "neutral")
    fused = affect_fields.get("affect_fused", "neutral")
    score = affect_fields.get("sentiment_score", 0.0)
    hints = {
        "happy": "The user seems happy.",
        "sad": "The user seems sad; be gentle.",
        "angry": "The user seems frustrated; stay calm and validating.",
        "fear": "The user seems anxious; be reassuring.",
        "surprise": "The user seems surprised.",
        "disgust": "The user seems uncomfortable; be tactful.",
        "neutral": "The user seems neutral; stay warm and engaged.",
    }
    base = hints.get(fused, hints["neutral"])
    return (
        "%s Fused affect=%s (visual=%s, VADER sentiment=%s, compound=%.2f)."
        % (base, fused, vis, sent, score)
    )


class VisualEmotionTracker(object):
    """Thread-safe cache of emotiondetect_result (optional)."""

    def __init__(self):
        import rospy
        from std_msgs.msg import String

        self._lock = threading.Lock()
        self._emotion = "neutral"
        self._sub = rospy.Subscriber(
            "emotiondetect_result", String, self._cb, queue_size=10
        )

    def _cb(self, msg):
        with self._lock:
            self._emotion = parse_visual_emotion_msg(msg.data)

    def current(self):
        with self._lock:
            return self._emotion


def load_vader_analyzer():
    try:
        import nltk
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
    except ImportError as e:
        raise ImportError(
            "nltk required for VADER. In Docker: "
            "bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh"
        ) from e
    try:
        nltk.data.find("sentiment/vader_lexicon.zip")
    except LookupError:
        nltk.download("vader_lexicon", quiet=True)
    return SentimentIntensityAnalyzer()
