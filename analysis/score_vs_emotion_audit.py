#!/usr/bin/env python3
"""Audit sentiment_score vs 7 emotion labels (percy_data, 30 sessions)."""
from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path

from cross_modal_consistency import EMOTIONS, load_chat_history
from merci_session_discovery import iter_all_sessions

OUT = Path(__file__).parent / "score_vs_emotion_audit.txt"

# Expected score sign by emotion (naive valence prior)
EXPECTED = {
    "happy": "pos",
    "neutral": "any",
    "sad": "neg",
    "fear": "neg",
    "angry": "neg",
    "disgust": "neg",
    "surprise": "any",
}


def score_sign(score: float, thr: float) -> str:
    if score > thr:
        return "pos"
    if score < -thr:
        return "neg"
    return "neu"


def main() -> None:
    by_em: dict[str, list[float]] = defaultdict(list)
    rows = []
    for sid, path in iter_all_sessions():
        for msg in load_chat_history(path):
            if msg.get("role") != "user":
                continue
            em = str(msg.get("emotion") or msg.get("emotion_visual") or "").lower().strip()
            if em not in EMOTIONS:
                continue
            sc = msg.get("sentiment_score")
            if sc is None:
                continue
            try:
                s = float(sc)
            except (TypeError, ValueError):
                continue
            by_em[em].append(s)
            rows.append((em, s, str(msg.get("sentiment", "")).lower()))

    lines = [
        "sentiment_score vs 7 emotion labels (n with score)",
        "=" * 60,
        f"Total turns with score: {len(rows)}",
        "",
    ]

    for em in EMOTIONS:
        vals = by_em[em]
        if not vals:
            lines.append(f"{em}: n=0")
            continue
        vals_sorted = sorted(vals)
        n = len(vals)
        med = statistics.median(vals)
        mean = statistics.mean(vals)
        q = statistics.quantiles(vals, n=4) if n >= 4 else [min(vals), med, max(vals)]
        pos = sum(1 for v in vals if v > 0.05)
        neu = sum(1 for v in vals if -0.05 <= v <= 0.05)
        neg = sum(1 for v in vals if v < -0.05)
        lines.append(
            f"{em:10s} n={n:4d}  mean={mean:+.3f} med={med:+.3f}  "
            f"IQR=[{q[0]:+.3f},{q[2]:+.3f}]  score>0.05:{pos:4d}  "
            f"|score|<=0.05:{neu:4d}  score<-0.05:{neg:4d}"
        )

    # Conflict variants using score only
    lines.extend(["", "Conflict rules using score (threshold on sign):", ""])

    def count_conflict(thr: float, em_map: dict) -> tuple[int, dict]:
        sub = defaultdict(int)
        n_conf = 0
        for em, s, _ in rows:
            exp = em_map.get(em, "any")
            if exp == "any":
                continue
            sign = score_sign(s, thr)
            bad = (exp == "pos" and sign == "neg") or (exp == "neg" and sign == "pos")
            if bad:
                n_conf += 1
                sub[f"{em}|score={sign}"] += 1
        return n_conf, sub

    paper_map = {
        "happy": "pos", "sad": "neg", "fear": "neg", "angry": "neg",
        "disgust": "neg", "neutral": "any", "surprise": "any",
    }
    for thr in (0.05, 0.15, 0.30):
        nc, sub = count_conflict(thr, paper_map)
        lines.append(f"  Expected sign + thr={thr}: {nc} conflicts ({100*nc/len(rows):.1f}%)")
        for k, v in sorted(sub.items(), key=lambda x: -x[1])[:6]:
            lines.append(f"    {k}: {v}")

    # disgust as any
    relaxed = {**paper_map, "disgust": "any"}
    nc, _ = count_conflict(0.05, relaxed)
    lines.append(f"  disgust=any + thr=0.05: {nc} ({100*nc/len(rows):.1f}%)")

    # Field vs score-sign agreement
    agree = sum(
        1 for em, s, sn in rows
        if sn in ("positive", "neutral", "negative")
        and score_sign(s, 0.05) in ("pos", "neu", "neg")
        and (
            (sn == "positive" and score_sign(s, 0.05) == "pos")
            or (sn == "neutral" and score_sign(s, 0.05) == "neu")
            or (sn == "negative" and score_sign(s, 0.05) == "neg")
        )
    )
    lines.extend([
        "",
        f"sentiment field agrees with score_sign(thr=0.05): {agree}/{len(rows)} "
        f"({100*agree/len(rows):.1f}%)",
    ])

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
