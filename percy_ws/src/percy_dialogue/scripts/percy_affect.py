#!/usr/bin/env python3
"""
MERCI / PERCY affect: VADER (text) + visual FER, 0.6/0.4 fusion (paper default).

Visual channel (pick one on the robot):
  - emotiondetect_result (std_msgs/String) — PERCY emotion_model/streamdata.py on laptop
  - pal_detection_msgs/FaceDetections — optional PAL fallback (not MERCI default)

Text channel:
  - NLTK VADER on Whisper transcript (compound thresholds ±0.05)
"""
from __future__ import print_function

import threading

VALID_EMOTIONS = ("angry", "disgust", "fear", "happy", "neutral", "sad", "surprise")

# VADER 3-class -> soft 7-class text distribution (MERCI / percy_affect legacy).
_SENTIMENT_TO_DIST = {
    "positive": {"happy": 0.72, "surprise": 0.18, "neutral": 0.10},
    "negative": {"sad": 0.45, "angry": 0.30, "disgust": 0.15, "fear": 0.10},
    "neutral": {"neutral": 1.0},
}

# Valence buckets for cross-modal conflict (journal Section 5).
_VISUAL_VALENCE = {
    "happy": "positive",
    "surprise": "positive",
    "neutral": "neutral",
    "sad": "negative",
    "angry": "negative",
    "disgust": "negative",
    "fear": "negative",
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


def emotion_from_face_detection(face):
    """Argmax over PAL FaceDetection emotion_*_confidence fields."""
    pairs = (
        ("angry", float(getattr(face, "emotion_anger_confidence", 0.0) or 0.0)),
        ("disgust", float(getattr(face, "emotion_disgust_confidence", 0.0) or 0.0)),
        ("fear", float(getattr(face, "emotion_fear_confidence", 0.0) or 0.0)),
        ("happy", float(getattr(face, "emotion_happiness_confidence", 0.0) or 0.0)),
        ("neutral", float(getattr(face, "emotion_neutral_confidence", 0.0) or 0.0)),
        ("sad", float(getattr(face, "emotion_sadness_confidence", 0.0) or 0.0)),
        ("surprise", float(getattr(face, "emotion_surprise_confidence", 0.0) or 0.0)),
    )
    label, score = max(pairs, key=lambda x: x[1])
    if score <= 0.0:
        return "neutral"
    return label


def vader_sentiment(analyzer, text):
    """Returns (polarity_label, compound_score). polarity in {positive, neutral, negative}."""
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
    fused = {
        k: w_vis * p_vis.get(k, 0.0) + w_txt * p_txt.get(k, 0.0) for k in VALID_EMOTIONS
    }
    fused = _normalize_dist(fused)
    label = max(fused, key=fused.get)
    confidence = fused[label]
    return label, confidence, fused


def cross_modal_valence_conflict(visual_label, sentiment_label):
    """True when visual emotion valence != VADER 3-class valence."""
    v_vis = _VISUAL_VALENCE.get((visual_label or "neutral").lower(), "neutral")
    v_txt = sentiment_label if sentiment_label in ("positive", "neutral", "negative") else "neutral"
    return v_vis != v_txt


def analyze_user_affect(
    analyzer,
    transcript,
    visual_emotion=None,
    w_vis=0.6,
    w_txt=0.4,
):
    """
    Turn-level affect for chat_history / MERCI cross-modal analysis.

    visual_emotion: latest FER label or None -> neutral one-hot.
    """
    sentiment, compound = vader_sentiment(analyzer, transcript)
    p_txt = _normalize_dist(dict(_SENTIMENT_TO_DIST[sentiment]))
    vis_label = parse_visual_emotion_msg(visual_emotion) if visual_emotion else "neutral"
    p_vis = _one_hot(vis_label)
    fused_label, fused_conf, fused_dist = fuse_emotion_distributions(
        p_vis, p_txt, w_vis=w_vis, w_txt=w_txt
    )
    conflict = cross_modal_valence_conflict(vis_label, sentiment)
    return {
        "emotion_visual": vis_label,
        "sentiment": sentiment,
        "sentiment_score": round(compound, 4),
        "affect_fused": fused_label,
        "affect_fused_confidence": round(fused_conf, 4),
        "affect_fusion_weights": {"visual": w_vis, "text": w_txt},
        "affect_fused_distribution": {k: round(fused_dist[k], 4) for k in VALID_EMOTIONS},
        "cross_modal_valence_conflict": conflict,
    }


def empathy_system_note(affect_fields):
    """Short English note for optional GPT system injection."""
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
    """
    Thread-safe cache of user visual emotion.

    Subscribes to emotiondetect_result (String) and/or FaceDetections.
    Latest non-neutral update wins; falls back to neutral.
    """

    def __init__(
        self,
        string_topic="emotiondetect_result",
        face_topic="",
    ):
        import rospy

        self._lock = threading.Lock()
        self._emotion = "neutral"
        self._subs = []

        if string_topic:
            from std_msgs.msg import String

            self._subs.append(
                rospy.Subscriber(string_topic, String, self._cb_string, queue_size=10)
            )
            rospy.loginfo("VisualEmotionTracker: String topic=%s", string_topic)

        if face_topic:
            try:
                from pal_detection_msgs.msg import FaceDetections

                self._subs.append(
                    rospy.Subscriber(
                        face_topic, FaceDetections, self._cb_faces, queue_size=5
                    )
                )
                rospy.loginfo("VisualEmotionTracker: FaceDetections topic=%s", face_topic)
            except ImportError:
                rospy.logwarn(
                    "pal_detection_msgs not available; face_topic %s ignored",
                    face_topic,
                )

    def _cb_string(self, msg):
        emo = parse_visual_emotion_msg(msg.data)
        with self._lock:
            self._emotion = emo

    def _cb_faces(self, msg):
        if not msg.faces:
            return
        face = msg.faces[0]
        emo = emotion_from_face_detection(face)
        with self._lock:
            self._emotion = emo

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
