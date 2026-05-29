#!/usr/bin/env python3
"""Summarise human conflict validation exports (§4.1).

Compares annotator ``human_conflict`` against deployment ``auto_rule_pred``.
Verifies auto labels against MERCI normalized sessions via ``user_turn_number``.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from merci_normalized_media import NORMALIZED_MEDIA_ROOT, load_session_messages
from run_downstream_benchmarks import classify_valence_conflict

OUT_DIR = Path(__file__).parent
MEDIA_ROOT = NORMALIZED_MEDIA_ROOT
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 42


def verify_auto_labels(rows: list[dict]) -> tuple[int, int]:
    """Return (n_matched, n_auto_mismatch) using session + user_turn_number."""
    matched = mism = 0
    for r in rows:
        sid = r["session_id"]
        utn = int(r["user_turn_number"])
        session_dir = MEDIA_ROOT / sid
        if not session_dir.exists():
            continue
        user_msgs = [m for m in load_session_messages(session_dir) if m.get("role") == "user"]
        if utn < 1 or utn > len(user_msgs):
            continue
        m = user_msgs[utn - 1]
        em = str(m.get("emotion_visual") or m.get("emotion") or "").lower()
        sn = str(m.get("sentiment") or "").lower()
        if em not in {"happy", "sad", "angry", "disgust", "fear", "surprise", "neutral"}:
            continue
        if sn not in {"positive", "neutral", "negative"}:
            continue
        corpus_auto = int(classify_valence_conflict(em, sn) == "conflict")
        matched += 1
        if corpus_auto != int(r["auto_rule_pred"]):
            mism += 1
    return matched, mism


def confusion_metrics(rows: list[dict]) -> dict:
    tp = sum(1 for r in rows if int(r["auto_rule_pred"]) == 1 and int(r["human_conflict"]) == 1)
    tn = sum(1 for r in rows if int(r["auto_rule_pred"]) == 0 and int(r["human_conflict"]) == 0)
    fp = sum(1 for r in rows if int(r["auto_rule_pred"]) == 1 and int(r["human_conflict"]) == 0)
    fn = sum(1 for r in rows if int(r["auto_rule_pred"]) == 0 and int(r["human_conflict"]) == 1)
    n = len(rows)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = (tp + tn) / n if n else 0.0
    p_auto = sum(int(r["auto_rule_pred"]) for r in rows) / n
    p_human = sum(int(r["human_conflict"]) for r in rows) / n
    pe = p_auto * p_human + (1 - p_auto) * (1 - p_human)
    kappa = (acc - pe) / (1 - pe) if pe != 1.0 else 0.0
    return {
        "n": n,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "accuracy": acc,
        "kappa": kappa,
        "auto_positive_rate": p_auto,
        "human_positive_rate": p_human,
    }


def session_bootstrap_ci(rows: list[dict], key: str, b: int = BOOTSTRAP_B) -> tuple[float, float, float]:
    by_sess: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sess[r["session_id"]].append(r)
    sessions = list(by_sess)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    vals = []
    for _ in range(b):
        pick = rng.choice(sessions, size=len(sessions), replace=True)
        sub = []
        for s in pick:
            sub.extend(by_sess[s])
        vals.append(confusion_metrics(sub)[key])
    point = confusion_metrics(rows)[key]
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "csv",
        nargs="?",
        default=str(OUT_DIR / "colleague_ar.csv"),
        help="Annotation export CSV",
    )
    ap.add_argument("-o", "--out", default=None, help="JSON summary path")
    args = ap.parse_args()

    path = Path(args.csv)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    annotators = sorted({r.get("annotator_id", "") for r in rows})
    matched, mism = verify_auto_labels(rows)
    m = confusion_metrics(rows)
    m["annotators"] = annotators
    m["n_sessions"] = len({r["session_id"] for r in rows})
    m["corpus_auto_verified"] = matched
    m["corpus_auto_mismatches"] = mism
    for stat in ("precision", "recall", "f1", "accuracy"):
        p, lo, hi = session_bootstrap_ci(rows, stat)
        m[f"{stat}_ci"] = [lo, hi]

    out = Path(args.out) if args.out else OUT_DIR / f"human_conflict_validation_{path.stem}.json"
    out.write_text(json.dumps(m, indent=2), encoding="utf-8")
    print(json.dumps(m, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
