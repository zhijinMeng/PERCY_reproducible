#!/usr/bin/env python3
"""Summarize §4.1 human conflict annotations → Table 3/4 + LaTeX snippets.

Expects adjudicated gold in ``human_conflict_annotations.csv`` (one row per turn).
Optional ``human_conflict_annotations_raw.csv`` for Cohen's kappa (pre-adjudication).

Example::

    python3 summarize_human_conflict.py \\
        human_conflict_annotations.csv \\
        -o human_conflict_results.md
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_int(x) -> int | None:
    if x is None or x == "":
        return None
    return int(x)


def confusion_matrix(rows: list[dict]) -> dict[str, int]:
    """auto_rule_pred vs human_conflict (adjudicated rows)."""
    tp = fp = fn = tn = 0
    for r in rows:
        auto = to_int(r.get("auto_rule_pred") or r.get("auto_conflict"))
        human = to_int(r.get("human_conflict"))
        if auto is None or human is None:
            continue
        if auto == 1 and human == 1:
            tp += 1
        elif auto == 1 and human == 0:
            fp += 1
        elif auto == 0 and human == 1:
            fn += 1
        else:
            tn += 1
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn}


def prf1(cm: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn = cm["TP"], cm["FP"], cm["FN"]
    n = tp + fp + fn + cm["TN"]
    prec = tp / (tp + fp) if (tp + fp) else None
    rec = tp / (tp + fn) if (tp + fn) else None
    if prec is not None and rec is not None and (prec + rec) > 0:
        f1 = 2 * prec * rec / (prec + rec)
    else:
        f1 = None
    human_pos = (tp + fn) / n if n else None
    return {
        "n": n,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "human_positive_rate": human_pos,
    }


def cohens_kappa(pairs: list[tuple[int, int]]) -> float | None:
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for a, b in pairs if a == b) / n
    c0 = Counter(a for a, _ in pairs)
    c1 = Counter(b for _, b in pairs)
    pe = sum((c0[k] / n) * (c1[k] / n) for k in (0, 1))
    if math.isclose(1.0 - pe, 0.0):
        return None
    return (po - pe) / (1.0 - pe)


def kappa_from_raw(raw_path: Path) -> tuple[float | None, int]:
    """κ on double-annotated turns (two annotators, not adjudicated)."""
    rows = read_csv(raw_path)
    by_turn: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for r in rows:
        if to_int(r.get("adjudicated")) == 1:
            continue
        tid = r.get("turn_id") or f"{r.get('session_id')}__u{int(r.get('user_turn_number', 0)):04d}"
        ann = r.get("annotator_id", "")
        h = to_int(r.get("human_conflict"))
        if h is None:
            continue
        by_turn[tid].append((ann, h))
    pairs: list[tuple[int, int]] = []
    for labels in by_turn.values():
        if len(labels) < 2:
            continue
        # first two distinct annotators
        seen = {}
        for ann, h in labels:
            if ann not in seen:
                seen[ann] = h
            if len(seen) >= 2:
                break
        if len(seen) >= 2:
            a, b = list(seen.values())[:2]
            pairs.append((a, b))
    return cohens_kappa(pairs), len(pairs)


def format_pct(x: float | None) -> str:
    return f"{100.0 * x:.1f}\\%" if x is not None else "--"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", type=Path, help="human_conflict_annotations.csv")
    parser.add_argument("-o", "--output", type=Path, default=None)
    parser.add_argument("--raw", type=Path, default=None, help="raw dual-annotator CSV for kappa")
    args = parser.parse_args()

    rows = read_csv(args.annotations)
    gold = [r for r in rows if to_int(r.get("adjudicated", 1)) == 1]
    if not gold:
        gold = rows

    cm = confusion_matrix(gold)
    stats = prf1(cm)
    kappa, kappa_n = (None, 0)
    raw_path = args.raw or args.annotations.parent / "human_conflict_annotations_raw.csv"
    if raw_path.exists():
        kappa, kappa_n = kappa_from_raw(raw_path)

    lines = [
        "# Human conflict validation (§4.1)",
        "",
        "## Table 3 (stratified sample)",
        "",
        "| | Human: No conflict | Human: Conflict | Total |",
        "|--|-------------------|-----------------|-------|",
        f"| Auto: conflict | {cm['FP']} (FP) | {cm['TP']} (TP) | {cm['TP'] + cm['FP']} |",
        f"| Auto: no conflict | {cm['TN']} (TN) | {cm['FN']} (FN) | {cm['TN'] + cm['FN']} |",
        f"| Total | {cm['FP'] + cm['TN']} | {cm['TP'] + cm['FN']} | {stats['n']} |",
        "",
        "## Table 4",
        "",
        f"| Quantity | Result |",
        f"|----------|--------|",
        f"| Sampled turns (total) | {stats['n']} |",
        f"| Double-annotated pairs (κ subset) | {kappa_n} |",
        f"| Cohen's κ | {kappa:.3f} |" if kappa is not None else "| Cohen's κ | -- |",
        f"| Precision | {stats['precision']:.3f} |" if stats["precision"] is not None else "| Precision | -- |",
        f"| Recall | {stats['recall']:.3f} |" if stats["recall"] is not None else "| Recall | -- |",
        f"| F1 | {stats['f1']:.3f} |" if stats["f1"] is not None else "| F1 | -- |",
        f"| Human-positive rate | {stats['human_positive_rate']:.3f} |"
        if stats["human_positive_rate"] is not None
        else "| Human-positive rate | -- |",
        "",
        "## LaTeX (paste into main.tex)",
        "",
        "% Table 3 cells",
        f"% TP={cm['TP']} FP={cm['FP']} FN={cm['FN']} TN={cm['TN']}",
        "",
        "% Table 4",
        f"% n={stats['n']} kappa={kappa:.2f} P={stats['precision']:.2f} R={stats['recall']:.2f} F1={stats['f1']:.2f}"
        if stats["precision"] is not None and kappa is not None and stats["f1"] is not None
        else "% fill after annotation",
        "",
    ]

    if stats["precision"] is not None and stats["recall"] is not None:
        if stats["precision"] > stats["recall"]:
            lines.append(
                "**Interpretation:** Precision > Recall → deployed rule is **conservative** "
                "(fewer automatic flags; flagged turns are more often human-confirmed)."
            )
        elif stats["recall"] > stats["precision"]:
            lines.append(
                "**Interpretation:** Recall > Precision → deployed rule is **liberal** "
                "(over-flags relative to human perception)."
            )
        else:
            lines.append("**Interpretation:** Precision ≈ Recall on this sample.")

    text = "\n".join(lines) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    print(text)


if __name__ == "__main__":
    main()
