"""Turn-level cross-modal consistency analysis on MERCI.

For each user turn, MERCI records both a visual-channel emotion label
(``emotion``; one of happy/neutral/sad/fear/angry/disgust/surprise) and a
text-channel sentiment polarity (``sentiment``; positive/neutral/negative)
plus a continuous ``sentiment_score``. This script quantifies how the two
channels co-occur at the n=1,860 turn level, which turn classes generate
cross-modal conflict (visual positive vs textual negative or vice versa),
and how per-session conflict rate relates to session-level outcomes.

Outputs (all under the ``analysis/`` sub-folder):

* ``cross_modal_confusion.csv``  -- 7x3 visual-emotion x text-sentiment
  contingency table (counts and row-normalised percentages).
* ``cross_modal_per_session.csv`` -- per-session counts of
  consistent / neutral / conflict turns and conflict rate.
* ``cross_modal_conflict_turns.csv`` -- the subset of turns flagged as
  cross-modal conflict, with content truncated to 120 characters for
  inspection and for downstream stratified-ablation slicing.
* ``cross_modal_summary.txt`` -- human-readable summary used to fill in
  Section 6 of the paper.

Running the script::

    python analysis/cross_modal_consistency.py

requires no external dependencies beyond the Python standard library.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

OUT_DIR = Path(__file__).parent

# Visual-channel emotion vocabulary (MERCI schema); ``unknown`` is dropped.
EMOTIONS = ["happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"]
SENTIMENTS = ["positive", "neutral", "negative"]

# A turn is flagged as a "cross-modal conflict" when the visual affect and
# the textual polarity disagree in valence:
#   - visual in {happy}  and  sentiment == "negative"
#   - visual in {sad, angry, disgust, fear}  and  sentiment == "positive"
# ``surprise`` is treated as valence-ambiguous and is not counted as a
# conflict source on its own. ``neutral`` visual or ``neutral`` sentiment
# is a "partial" case, reported separately.
VISUAL_POSITIVE = {"happy"}
VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def iter_session_files() -> list[tuple[str, Path]]:
    """Return (session_id, session_dir) for normalized_media (30 sessions)."""
    from merci_normalized_media import iter_normalized_sessions

    return iter_normalized_sessions()


def load_chat_history(session_dir: Path) -> list[dict]:
    from merci_normalized_media import load_session_messages

    return load_session_messages(session_dir)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def classify_turn(emotion: str, sentiment: str) -> str:
    """Return one of {consistent, neutral, conflict, other}.

    * consistent : visual and textual polarity agree in valence
    * neutral    : at least one of the two channels is neutral
    * conflict   : valences disagree (happy vs negative, or neg-emotion vs positive)
    * other      : surprise or unknown valence combinations
    """

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


def main() -> None:
    sessions = iter_session_files()
    print(f"Found {len(sessions)} sessions with chat_history.json")

    # (emotion, sentiment) -> count
    cell_counts: Counter = Counter()
    per_session_stats: dict[str, Counter] = defaultdict(Counter)
    conflict_rows: list[dict] = []
    total_user_turns = 0
    dropped_unknown = 0

    for sid, session_dir in sessions:
        messages = load_chat_history(session_dir)
        for i, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            em = str(
                msg.get("emotion") or msg.get("emotion_visual") or ""
            ).lower().strip()
            sn = str(msg.get("sentiment", "")).lower().strip()
            if em not in EMOTIONS or sn not in SENTIMENTS:
                dropped_unknown += 1
                continue
            total_user_turns += 1
            cell_counts[(em, sn)] += 1
            cls = classify_turn(em, sn)
            per_session_stats[sid][cls] += 1
            if cls == "conflict":
                conflict_rows.append({
                    "session_id": sid,
                    "turn_index": i,
                    "emotion": em,
                    "sentiment": sn,
                    "sentiment_score": msg.get("sentiment_score"),
                    "sentiment_confidence": msg.get("sentiment_confidence"),
                    "emotion_visual_confidence": msg.get("emotion_visual_confidence"),
                    "content": str(msg.get("content", ""))[:120],
                })

    # ------------------------------------------------------------------
    # 7x3 confusion matrix
    # ------------------------------------------------------------------
    confusion_p = OUT_DIR / "cross_modal_confusion.csv"
    with confusion_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["emotion", "n_total"] + [f"{s}_n" for s in SENTIMENTS]
                   + [f"{s}_pct" for s in SENTIMENTS])
        for em in EMOTIONS:
            row_total = sum(cell_counts.get((em, s), 0) for s in SENTIMENTS)
            ns = [cell_counts.get((em, s), 0) for s in SENTIMENTS]
            pcts = [
                (100.0 * n / row_total) if row_total else 0.0 for n in ns
            ]
            w.writerow([em, row_total] + ns + [f"{p:.1f}" for p in pcts])
    print(f"Wrote {confusion_p}")

    # ------------------------------------------------------------------
    # per-session conflict statistics
    # ------------------------------------------------------------------
    per_session_p = OUT_DIR / "cross_modal_per_session.csv"
    with per_session_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "session_id", "n_turns", "consistent", "neutral", "conflict",
            "other", "conflict_rate_pct",
        ])
        for sid in sorted(per_session_stats):
            c = per_session_stats[sid]
            n_turns = sum(c.values())
            conflict = c.get("conflict", 0)
            rate = (100.0 * conflict / n_turns) if n_turns else 0.0
            w.writerow([
                sid, n_turns,
                c.get("consistent", 0), c.get("neutral", 0),
                conflict, c.get("other", 0),
                f"{rate:.1f}",
            ])
    print(f"Wrote {per_session_p}")

    # ------------------------------------------------------------------
    # conflict-turn inspection sheet
    # ------------------------------------------------------------------
    conflict_p = OUT_DIR / "cross_modal_conflict_turns.csv"
    with conflict_p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "session_id", "turn_index", "emotion", "sentiment",
                "sentiment_score", "sentiment_confidence",
                "emotion_visual_confidence", "content",
            ],
            extrasaction="ignore",
        )
        w.writeheader()
        for row in conflict_rows:
            w.writerow(row)
    print(f"Wrote {conflict_p} ({len(conflict_rows)} conflict turns)")

    # ------------------------------------------------------------------
    # text summary for the paper
    # ------------------------------------------------------------------
    summary_p = OUT_DIR / "cross_modal_summary.txt"
    totals_by_class = Counter()
    for c in per_session_stats.values():
        totals_by_class.update(c)
    n_conflict = totals_by_class.get("conflict", 0)
    n_consistent = totals_by_class.get("consistent", 0)
    n_neutral = totals_by_class.get("neutral", 0)
    n_other = totals_by_class.get("other", 0)
    with summary_p.open("w", encoding="utf-8") as f:
        f.write("Cross-modal consistency analysis summary\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Sessions scanned : {len(sessions)}\n")
        f.write(f"User turns kept  : {total_user_turns}\n")
        f.write(f"User turns dropped (unknown emotion or sentiment): "
                f"{dropped_unknown}\n\n")
        f.write("Turn-class counts (n and %):\n")
        for name, n in [
            ("consistent", n_consistent),
            ("neutral (>=1 channel neutral)", n_neutral),
            ("conflict (valence mismatch)", n_conflict),
            ("other (e.g. surprise)", n_other),
        ]:
            pct = (100.0 * n / total_user_turns) if total_user_turns else 0.0
            f.write(f"  {name:40s}: {n:5d}  ({pct:.1f}%)\n")
        f.write("\n")
        f.write("7x3 visual-emotion x text-sentiment confusion (n):\n")
        f.write(f"  {'emotion':10s}" + "".join(
            f" {s:>10s}" for s in SENTIMENTS) + f" {'total':>10s}\n")
        for em in EMOTIONS:
            ns = [cell_counts.get((em, s), 0) for s in SENTIMENTS]
            total = sum(ns)
            f.write(f"  {em:10s}" + "".join(f" {n:10d}" for n in ns)
                    + f" {total:10d}\n")
        # Per-session conflict rate distribution
        rates = []
        for c in per_session_stats.values():
            nt = sum(c.values())
            if nt:
                rates.append(100.0 * c.get("conflict", 0) / nt)
        if rates:
            rates_sorted = sorted(rates)
            n = len(rates_sorted)
            median = rates_sorted[n // 2] if n % 2 == 1 else \
                0.5 * (rates_sorted[n // 2 - 1] + rates_sorted[n // 2])
            q1 = rates_sorted[n // 4]
            q3 = rates_sorted[(3 * n) // 4]
            f.write(f"\nPer-session conflict rate (%): median={median:.1f}, "
                    f"IQR=[{q1:.1f}, {q3:.1f}], min={min(rates):.1f}, "
                    f"max={max(rates):.1f}\n")
    print(f"Wrote {summary_p}")


if __name__ == "__main__":
    main()
