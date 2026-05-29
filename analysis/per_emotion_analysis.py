"""Per-emotion distribution and BLEU breakdown across MERCI sessions.

Reads all chat_history_asr_aligned_large_v3.json under
  fixed_data/Ari Robot/  (all three sub-folders: _人工修订, _已处理_含音轨mp4, _已处理_无音轨mp4)
and cross-references ablation run_full.jsonl / run_no_visual.jsonl to compute
per-emotion BLEU (Full vs No-visual) using sacrebleu.

Outputs:
  Claude_Writing/per_emotion_distribution.csv   -- turn counts per emotion
  Claude_Writing/per_emotion_bleu.csv           -- per-emotion BLEU Full / No-visual / delta
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
from collections import defaultdict
from sacrebleu.metrics import BLEU

# ── paths ──────────────────────────────────────────────────────────────────
FIXED_DATA = Path(
    r"c:\Users\z5430888\OneDrive - UNSW\Research Project\OneDrive_2026-04-02\fixed_data\Ari Robot"
)
SESSIONS_DIR = Path(
    r"c:\Users\z5430888\OneDrive - UNSW\Research Project\OneDrive_2026-04-02"
    r"\Paper_writing\MTAP_PERCY_shell\ablation_offline\outputs\batch_20260416_221554\sessions"
)
OUT_DIR = Path(__file__).parent  # Claude_Writing/

EMOTION_ORDER = ["happy", "neutral", "sad", "fear", "angry", "disgust", "surprise", "unknown"]


# ── helpers ─────────────────────────────────────────────────────────────────

def load_json(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(p: Path):
    rows = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── Step 1: collect per-session emotion distribution from fixed_data ─────────

def collect_emotion_distribution():
    """Walk all chat_history_asr_aligned_large_v3.json, extract user turns."""
    emotion_counts: dict[str, int] = defaultdict(int)
    session_emotions: dict[str, dict[str, list[str]]] = {}  # session_id -> {emotion: [turn indices]}

    for sub in FIXED_DATA.iterdir():
        if not sub.is_dir():
            continue
        for session_dir in sub.iterdir():
            if not session_dir.is_dir():
                continue
            chat_p = session_dir / "chat_history_asr_aligned_large_v3.json"
            if not chat_p.exists():
                continue
            data = load_json(chat_p)
            messages = data.get("messages", [])
            sess_id = session_dir.name
            session_emotions[sess_id] = defaultdict(list)
            for i, msg in enumerate(messages):
                if msg.get("role") != "user":
                    continue
                em = str(msg.get("emotion", "unknown")).lower().strip()
                if em not in EMOTION_ORDER:
                    em = "unknown"
                emotion_counts[em] += 1
                session_emotions[sess_id][em].append(str(i))

    return dict(emotion_counts), session_emotions


# ── Step 2: build turn index from ablation jsonl ─────────────────────────────
# Each ablation jsonl row has a 'reference' and 'hypothesis'.
# We need to align them to session turns to get the emotion label.
# Strategy: for each ablation session, read its corresponding fixed_data chat JSON
# to get the emotion sequence, then zip with ablation rows (user turns only).

def build_session_emotion_map() -> dict[str, list[str]]:
    """Pre-build a map: session_id -> ordered list of emotions for user turns."""
    result: dict[str, list[str]] = {}
    for chat_p in FIXED_DATA.rglob("chat_history_asr_aligned_large_v3.json"):
        session_id = chat_p.parent.name
        data = load_json(chat_p)
        emotions = []
        for msg in data.get("messages", []):
            if msg.get("role") == "user":
                em = str(msg.get("emotion", "unknown")).lower().strip()
                if em not in EMOTION_ORDER:
                    em = "unknown"
                emotions.append(em)
        result[session_id] = emotions
    return result


def get_session_emotion_sequence(session_id: str, em_map: dict[str, list[str]]) -> list[str]:
    return em_map.get(session_id, [])


def build_per_emotion_bleu_data(em_map: dict[str, list[str]]):
    """For each ablation session, align user-turn emotions to ablation hypotheses."""
    per_em_full: dict[str, list] = defaultdict(list)
    per_em_novis: dict[str, list] = defaultdict(list)
    per_em_refs: dict[str, list] = defaultdict(list)

    matched_sessions = 0
    unmatched_sessions = 0

    for sdir in sorted([p for p in SESSIONS_DIR.iterdir() if p.is_dir()]):
        full_p = sdir / "run_full.jsonl"
        novis_p = sdir / "run_no_visual.jsonl"
        if not full_p.exists() or not novis_p.exists():
            continue

        full_rows = load_jsonl(full_p)
        novis_rows = load_jsonl(novis_p)
        if len(full_rows) != len(novis_rows):
            continue

        emotions = get_session_emotion_sequence(sdir.name, em_map)

        if not emotions:
            unmatched_sessions += 1
        else:
            matched_sessions += 1

        emotion_idx = 0
        for rf, rn in zip(full_rows, novis_rows):
            if not rf.get("hypothesis") or not rn.get("hypothesis"):
                emotion_idx += 1
                continue
            if emotions and emotion_idx < len(emotions):
                em = emotions[emotion_idx]
            else:
                em = "unknown"
            per_em_refs[em].append(str(rf["reference"]))
            per_em_full[em].append(str(rf["hypothesis"]))
            per_em_novis[em].append(str(rn["hypothesis"]))
            emotion_idx += 1

    print(f"Matched sessions (fixed_data found): {matched_sessions}")
    print(f"Unmatched sessions (no fixed_data): {unmatched_sessions}")
    return per_em_refs, per_em_full, per_em_novis


def compute_bleu_for_emotion(refs, hyps_full, hyps_novis):
    if not refs:
        return None, None, None
    bleu = BLEU(effective_order=True)
    score_full = float(bleu.corpus_score(hyps_full, [refs]).score)
    score_novis = float(bleu.corpus_score(hyps_novis, [refs]).score)
    return score_full, score_novis, score_novis - score_full


# ── main ────────────────────────────────────────────────────────────────────

def main():
    print("=== Step 1: Emotion distribution from fixed_data ===")
    emotion_counts, _ = collect_emotion_distribution()
    total_turns = sum(emotion_counts.values())
    print(f"Total user turns: {total_turns}")
    for em in EMOTION_ORDER:
        n = emotion_counts.get(em, 0)
        print(f"  {em:12s}: {n:4d}  ({100*n/total_turns:.1f}%)")

    # write distribution CSV
    dist_csv = OUT_DIR / "per_emotion_distribution.csv"
    with dist_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["emotion", "n_turns", "pct"])
        for em in EMOTION_ORDER:
            n = emotion_counts.get(em, 0)
            w.writerow([em, n, f"{100*n/total_turns:.1f}"])
    print(f"Wrote: {dist_csv}")

    print("\n=== Step 2: Per-emotion BLEU (Full vs No-visual) ===")
    print("Building emotion map from fixed_data...")
    em_map = build_session_emotion_map()
    print(f"  emotion map loaded for {len(em_map)} sessions: {sorted(em_map.keys())}")
    per_em_refs, per_em_full, per_em_novis = build_per_emotion_bleu_data(em_map)

    bleu_rows = []
    for em in EMOTION_ORDER:
        refs = per_em_refs.get(em, [])
        hyps_full = per_em_full.get(em, [])
        hyps_novis = per_em_novis.get(em, [])
        n = len(refs)
        if n == 0:
            bleu_rows.append({"emotion": em, "n": 0, "bleu_full": None, "bleu_novis": None, "delta": None})
            continue
        bf, bn, delta = compute_bleu_for_emotion(refs, hyps_full, hyps_novis)
        bleu_rows.append({"emotion": em, "n": n, "bleu_full": bf, "bleu_novis": bn, "delta": delta})
        print(f"  {em:12s} n={n:4d}  BLEU_full={bf:.2f}  BLEU_novis={bn:.2f}  delta={delta:+.2f}")

    bleu_csv = OUT_DIR / "per_emotion_bleu.csv"
    with bleu_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["emotion", "n", "bleu_full", "bleu_novis", "delta"])
        w.writeheader()
        for r in bleu_rows:
            w.writerow(r)
    print(f"Wrote: {bleu_csv}")


if __name__ == "__main__":
    main()
