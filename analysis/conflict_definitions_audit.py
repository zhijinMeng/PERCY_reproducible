#!/usr/bin/env python3
"""Compare multiple cross-modal conflict definitions on percy_data (30 sessions)."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from merci_session_discovery import iter_all_sessions
from cross_modal_consistency import load_chat_history, EMOTIONS, SENTIMENTS

OUT = Path(__file__).parent

# --- Visual valence maps ---------------------------------------------------

# Paper / cross_modal_consistency.py (current)
PAPER_POS = {"happy"}
PAPER_NEG = {"sad", "angry", "disgust", "fear"}

# Ekman-style: disgust negative; surprise ambiguous
EKMAN_POS = {"happy"}
EKMAN_NEG = {"sad", "angry", "disgust", "fear"}
EKMAN_AMBIG = {"surprise", "neutral"}

# Relaxed visual: only happy vs {sad, angry, fear} — disgust treated as ambiguous
# (FER "disgust" often fires on focus/concentration in HRI, not semantic disgust)
RELAXED_POS = {"happy"}
RELAXED_NEG = {"sad", "angry", "fear"}
RELAXED_AMBIG = {"disgust", "surprise", "neutral"}


def text_from_score(score: float | None, thr: float = 0.05) -> str:
    if score is None:
        return "neutral"
    if score > thr:
        return "positive"
    if score < -thr:
        return "negative"
    return "neutral"


def visual_valence(em: str, pos: set[str], neg: set[str], ambig: set[str] | None = None) -> str:
    if ambig and em in ambig:
        return "ambiguous"
    if em == "neutral":
        return "neutral"
    if em in pos:
        return "positive"
    if em in neg:
        return "negative"
    return "ambiguous"


def is_conflict_paper(em: str, sn: str) -> bool:
    """Exact logic in classify_turn() when result == conflict."""
    if em == "neutral" or sn == "neutral":
        return False
    if em in PAPER_POS and sn == "negative":
        return True
    if em in PAPER_NEG and sn == "positive":
        return True
    return False


def is_conflict_both_non_neutral(
    em: str, sn: str, pos: set[str], neg: set[str], ambig: set[str] | None = None
) -> bool:
    vv = visual_valence(em, pos, neg, ambig)
    if vv == "neutral" or sn == "neutral" or vv == "ambiguous":
        return False
    if vv == "positive" and sn == "negative":
        return True
    if vv == "negative" and sn == "positive":
        return True
    return False


def is_conflict_strong(
    em: str, sn: str, score: float | None, min_abs_score: float = 0.30
) -> bool:
    if not is_conflict_paper(em, sn):
        return False
    if score is None:
        return True
    return abs(score) >= min_abs_score


def conflict_subtype(em: str, sn: str) -> str:
    if em == "happy" and sn == "negative":
        return "happy_face+text_neg"
    if em in PAPER_NEG and sn == "positive":
        return f"{em}_face+text_pos"
    return "other"


def main() -> None:
    rows: list[dict] = []
    for sid, path in iter_all_sessions():
        for i, msg in enumerate(load_chat_history(path)):
            if msg.get("role") != "user":
                continue
            em = str(msg.get("emotion") or msg.get("emotion_visual") or "").lower().strip()
            sn = str(msg.get("sentiment", "")).lower().strip()
            score = msg.get("sentiment_score")
            try:
                score_f = float(score) if score is not None else None
            except (TypeError, ValueError):
                score_f = None
            if em not in EMOTIONS:
                continue
            sn_score = text_from_score(score_f)
            row = {
                "session_id": sid,
                "turn_index": i,
                "emotion": em,
                "sentiment_field": sn,
                "sentiment_score": score_f,
                "sentiment_from_score": sn_score,
            }
            rows.append(row)

    n = len(rows)
    valid_sn = [r for r in rows if r["sentiment_field"] in SENTIMENTS]
    n_valid = len(valid_sn)

    defs: list[tuple[str, callable]] = [
        ("D1_paper_field", lambda r: is_conflict_paper(r["emotion"], r["sentiment_field"])),
        (
            "D2_score_polarity",
            lambda r: is_conflict_both_non_neutral(
                r["emotion"],
                r["sentiment_from_score"],
                PAPER_POS,
                PAPER_NEG,
            ),
        ),
        (
            "D3_relaxed_disgust_ambiguous",
            lambda r: is_conflict_both_non_neutral(
                r["emotion"],
                r["sentiment_field"],
                RELAXED_POS,
                RELAXED_NEG,
                RELAXED_AMBIG,
            ),
        ),
        (
            "D4_strong_|score|>=0.30",
            lambda r: is_conflict_strong(
                r["emotion"], r["sentiment_field"], r["sentiment_score"], 0.30
            ),
        ),
        (
            "D5_strong_|score|>=0.50",
            lambda r: is_conflict_strong(
                r["emotion"], r["sentiment_field"], r["sentiment_score"], 0.50
            ),
        ),
        (
            "D6_field_OR_score_mismatch",
            lambda r: is_conflict_paper(r["emotion"], r["sentiment_field"])
            or is_conflict_both_non_neutral(
                r["emotion"], r["sentiment_from_score"], PAPER_POS, PAPER_NEG
            ),
        ),
    ]

    # Field vs score disagreement
    field_score_mismatch = sum(
        1
        for r in valid_sn
        if r["sentiment_field"] in SENTIMENTS
        and r["sentiment_from_score"] != "neutral"
        and r["sentiment_field"] != r["sentiment_from_score"]
    )

    lines = [
        "Cross-modal CONFLICT definition audit (percy_data, 30 sessions)",
        "=" * 60,
        f"User turns with valid emotion: {n}",
        f"User turns with emotion + sentiment field: {n_valid}",
        f"sentiment field != score-derived polarity (non-neutral): {field_score_mismatch}",
        "",
        "CURRENT PAPER RULE (D1 = cross_modal_consistency.py)",
        "-" * 60,
        "Step 1: Use JSON fields emotion (visual) + sentiment (pos/neu/neg from VADER).",
        "Step 2: Map visual to valence:",
        "         happy -> positive",
        "         sad, angry, disgust, fear -> negative",
        "         neutral -> neutral (no valence claim)",
        "         surprise -> neither pos nor neg -> class 'other', NOT conflict",
        "Step 3: If EITHER channel is neutral -> class 'neutral', NOT conflict",
        "Step 4: CONFLICT iff:",
        "         (happy + negative text) OR (negative-valence face + positive text)",
        "",
        "Implications:",
        "  - disgust + positive text IS conflict (e.g. enthusiastic hobby talk)",
        "  - happy + weak VADER negative (-0.08) IS conflict (complaint/stress)",
        "  - neutral on either side removes turn from conflict denominator",
        "",
        "Counts by definition (on turns with valid sentiment field):",
        "",
    ]

    summary_rows = []
    for name, fn in defs:
        hits = [r for r in valid_sn if fn(r)]
        sub = Counter(conflict_subtype(r["emotion"], r["sentiment_field"]) for r in hits)
        pct = 100.0 * len(hits) / n_valid if n_valid else 0
        lines.append(f"  {name}: {len(hits)} / {n_valid} = {pct:.1f}%")
        for k, v in sub.most_common():
            lines.append(f"      {k}: {v}")
        summary_rows.append({"definition": name, "n_conflict": len(hits), "pct": f"{pct:.1f}"})

    # D1 cell breakdown (7x3 off-diagonal conflict cells)
    lines.extend(["", "D1 conflict cells (emotion x sentiment_field):", ""])
    cell_hits = Counter(
        (r["emotion"], r["sentiment_field"])
        for r in valid_sn
        if is_conflict_paper(r["emotion"], r["sentiment_field"])
    )
    for (em, sn), c in cell_hits.most_common():
        lines.append(f"  {em:10s} + {sn:8s}: {c}")

    # Turns where D1 but weak score
    weak = [
        r for r in valid_sn
        if is_conflict_paper(r["emotion"], r["sentiment_field"])
        and r["sentiment_score"] is not None
        and abs(r["sentiment_score"]) < 0.30
    ]
    lines.extend([
        "",
        f"D1 conflicts with |sentiment_score| < 0.30: {len(weak)} "
        f"({100*len(weak)/max(len([r for r in valid_sn if is_conflict_paper(r['emotion'], r['sentiment_field'])]),1):.1f}% of D1)",
    ])

    out_txt = OUT / "conflict_definitions_audit.txt"
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_csv = OUT / "conflict_definitions_summary.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["definition", "n_conflict", "pct"])
        w.writeheader()
        w.writerows(summary_rows)

    # Export D1 conflicts with subtype + scores for manual review
    detail = OUT / "conflict_turns_D1_paper.csv"
    with detail.open("w", newline="", encoding="utf-8") as f:
        fields = [
            "session_id", "turn_index", "subtype", "emotion", "sentiment_field",
            "sentiment_score", "sentiment_from_score",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in valid_sn:
            if not is_conflict_paper(r["emotion"], r["sentiment_field"]):
                continue
            w.writerow({
                **{k: r[k] for k in fields if k in r},
                "subtype": conflict_subtype(r["emotion"], r["sentiment_field"]),
            })

    print(out_txt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
