from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path


ROOT = Path(r"c:\Users\z5430888\OneDrive - UNSW\Research Project\OneDrive_2026-04-02")
FIXED_DATA_ROOT = ROOT / "fixed_data" / "Ari Robot"
MAPPING_CSV = ROOT / "Paper_writing" / "Claude_Writing" / "mapping" / "FINAL_session_post_mapping.csv"
OUT_DIR = ROOT / "Paper_writing" / "Claude_Writing" / "analysis_output"
OUT_CSV = OUT_DIR / "merci_turns.csv"

QUESTION_WORD_RE = re.compile(r"\b(who|what|where|when|why|how|is|are|do|does|can)\b", re.IGNORECASE)


def load_participant_mapping() -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not MAPPING_CSV.exists():
        return mapping
    with MAPPING_CSV.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            sid = (row.get("session_id") or "").strip()
            email = (row.get("email") or "").strip()
            if sid:
                # Use email where available; otherwise fallback to session id.
                mapping[sid] = email if email else sid
    return mapping


def split_words(text: str) -> list[str]:
    # "split by whitespace after lowercase" per your specification.
    return [w for w in text.lower().split() if w]


def as_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def textual_sentiment_label(score: float | None) -> str:
    if score is None:
        return "neu"
    if score > 0.05:
        return "pos"
    if score < -0.05:
        return "neg"
    return "neu"


def classify_consistency(visual_emotion: str, text_label: str) -> str:
    visual_valence = {
        "happy": "pos",
        "sad": "neg",
        "angry": "neg",
        "disgust": "neg",
        "fear": "neg",
        "surprise": "ambiguous",
        "neutral": "neu",
    }
    vv = visual_valence.get((visual_emotion or "").lower(), "ambiguous")
    t = text_label
    if vv == "ambiguous":
        return "visual_ambiguous"
    if vv == t:
        return "consistent"
    if vv == "neu" or t == "neu":
        return "one_neutral"
    return "conflict"


def contains_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if t.endswith("?"):
        return True
    return bool(QUESTION_WORD_RE.search(t))


def next_index_with_role(messages: list[dict], start_idx: int, role: str) -> int | None:
    for i in range(start_idx + 1, len(messages)):
        if messages[i].get("role") == role:
            return i
    return None


def build_rows_for_session(session_id: str, messages: list[dict], participant_id: str) -> list[dict]:
    user_positions = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    total_user_turns = len(user_positions)
    rows: list[dict] = []

    for turn_index, msg_idx in enumerate(user_positions):
        user_msg = messages[msg_idx]
        assistant_idx = next_index_with_role(messages, msg_idx, "assistant")
        next_user_idx = user_positions[turn_index + 1] if turn_index + 1 < total_user_turns else None

        assistant_msg = messages[assistant_idx] if assistant_idx is not None else {}
        next_user_msg = messages[next_user_idx] if next_user_idx is not None else {}

        u_text = str(user_msg.get("content", "") or "")
        r_text = str(assistant_msg.get("content", "") or "")

        u_words = split_words(u_text)
        r_words = split_words(r_text)

        u_start = as_float(user_msg.get("asr_start") or user_msg.get("t_start_sec"))
        u_end = as_float(user_msg.get("asr_end") or user_msg.get("t_end_sec"))
        r_start = as_float(assistant_msg.get("asr_start") or assistant_msg.get("t_start_sec"))
        r_end = as_float(assistant_msg.get("asr_end") or assistant_msg.get("t_end_sec"))
        nu_start = as_float(next_user_msg.get("asr_start") or next_user_msg.get("t_start_sec"))

        u_dur = (u_end - u_start) if (u_start is not None and u_end is not None) else None
        r_dur = (r_end - r_start) if (r_start is not None and r_end is not None) else None

        rr_lat = (r_start - u_end) if (r_start is not None and u_end is not None) else None
        ur_lat = (nu_start - r_end) if (nu_start is not None and r_end is not None) else None

        is_clean_rr = (rr_lat is not None) and (0 <= rr_lat <= 60)
        is_clean_ur = (ur_lat is not None) and (0 <= ur_lat <= 60)

        v_emotion = str(
            user_msg.get("emotion") or user_msg.get("emotion_visual") or ""
        ).lower().strip()
        s_score = as_float(user_msg.get("sentiment_score"))
        s_label = textual_sentiment_label(s_score)
        v_conf = ""
        dist = user_msg.get("affect_fused_distribution")
        if isinstance(dist, dict) and v_emotion in dist:
            v_conf = dist[v_emotion]
        elif user_msg.get("emotion_visual_confidence") is not None:
            v_conf = user_msg.get("emotion_visual_confidence")
        elif user_msg.get("affect_fused_confidence") is not None:
            v_conf = user_msg.get("affect_fused_confidence")
        fused = str(user_msg.get("affect_fused") or "").lower().strip()

        denom = (total_user_turns - 1) if total_user_turns > 1 else 1
        turn_norm = turn_index / denom

        topic_segment_id = turn_index // 3
        within_topic_position = turn_index % 3

        row = {
            # Identity
            "session_id": session_id,
            "participant_id": participant_id,
            "turn_index": turn_index,
            "turn_index_normalized": round(turn_norm, 6),
            # Topic structure
            "topic_segment_id": topic_segment_id,
            "within_topic_position": within_topic_position,
            "is_topic_opener": within_topic_position == 0,
            "is_topic_closer": within_topic_position == 2,
            # User side
            "user_utterance": u_text,
            "user_word_count": len(u_words),
            "user_utterance_duration_s": "" if u_dur is None else round(u_dur, 6),
            "contains_question": contains_question(u_text),
            # Robot side
            "robot_utterance": r_text,
            "robot_word_count": len(r_words),
            "robot_utterance_duration_s": "" if r_dur is None else round(r_dur, 6),
            # Latency
            "robot_response_latency": "" if rr_lat is None else round(rr_lat, 6),
            "user_response_latency": "" if ur_lat is None else round(ur_lat, 6),
            "is_clean_robot_latency": is_clean_rr,
            "is_clean_user_latency": is_clean_ur,
            # Multimodal labels
            "visual_emotion": v_emotion,
            "visual_emotion_confidence": "" if v_conf == "" else round(float(v_conf), 6),
            "textual_sentiment_score": "" if s_score is None else round(s_score, 6),
            "textual_sentiment_label": s_label,
            "fused_affect": fused,
            # Cross-modal consistency
            "cross_modal_consistency": classify_consistency(v_emotion, s_label),
        }
        rows.append(row)

    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    participant_map = load_participant_mapping()

    all_rows: list[dict] = []
    chat_files = sorted(FIXED_DATA_ROOT.rglob("chat_history_asr_aligned_large_v3.json"))

    for chat_path in chat_files:
        session_id = chat_path.parent.name
        participant_id = participant_map.get(session_id, session_id)

        with chat_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        messages = data.get("messages", [])
        all_rows.extend(build_rows_for_session(session_id, messages, participant_id))

    fieldnames = [
        "session_id",
        "participant_id",
        "turn_index",
        "turn_index_normalized",
        "topic_segment_id",
        "within_topic_position",
        "is_topic_opener",
        "is_topic_closer",
        "user_utterance",
        "user_word_count",
        "user_utterance_duration_s",
        "contains_question",
        "robot_utterance",
        "robot_word_count",
        "robot_utterance_duration_s",
        "robot_response_latency",
        "user_response_latency",
        "is_clean_robot_latency",
        "is_clean_user_latency",
        "visual_emotion",
        "visual_emotion_confidence",
        "textual_sentiment_score",
        "textual_sentiment_label",
        "fused_affect",
        "cross_modal_consistency",
    ]

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(row)

    # Quick summary for sanity checks.
    session_ids = sorted(set(r["session_id"] for r in all_rows))
    clean_rr = sum(1 for r in all_rows if r["is_clean_robot_latency"])
    clean_ur = sum(1 for r in all_rows if r["is_clean_user_latency"])
    cc_counts = {}
    for r in all_rows:
        cc = r["cross_modal_consistency"]
        cc_counts[cc] = cc_counts.get(cc, 0) + 1

    print(f"wrote: {OUT_CSV}")
    print(f"sessions: {len(session_ids)}")
    print(f"turns: {len(all_rows)}")
    print(f"clean_robot_latency: {clean_rr}")
    print(f"clean_user_latency: {clean_ur}")
    print(f"cross_modal_consistency: {cc_counts}")


if __name__ == "__main__":
    main()
