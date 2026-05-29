"""Paired bootstrap CIs for offline-replay ablation (Layer-2 Section 8).

Reads session-level score_*.json under
  Paper_writing/MTAP_PERCY_shell/ablation_offline/outputs/batch_20260416_221554/sessions
and reports paired (per-session) mean differences vs Full and a 95% bootstrap CI
for BLEU and BERTScore-F1 across the four ablations.

Usage (run from repo root or anywhere with the absolute path):
    python compute_paired_bootstrap.py
"""

from __future__ import annotations

import json
import csv
from pathlib import Path
import statistics
import random


SESSIONS_DIR = Path(
    r"c:\Users\z5430888\OneDrive - UNSW\Research Project\OneDrive_2026-04-02\\"
    r"Paper_writing\MTAP_PERCY_shell\ablation_offline\outputs\batch_20260416_221554\sessions"
)

ABLATIONS = ["no_visual", "no_sentiment", "no_persona", "short_history"]
METRICS = ["bleu", "bertscore_f1_mean"]


def load_score(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def collect_paired():
    rows = []
    for sdir in sorted([p for p in SESSIONS_DIR.iterdir() if p.is_dir()]):
        full_p = sdir / "score_full.json"
        if not full_p.exists():
            continue
        full = load_score(full_p)
        if full.get("n", 0) <= 0:
            continue
        row = {"session": sdir.name, **{f"full_{m}": full.get(m) for m in METRICS}}
        for ab in ABLATIONS:
            ap = sdir / f"score_{ab}.json"
            if not ap.exists():
                row[f"{ab}_ok"] = False
                continue
            d = load_score(ap)
            row[f"{ab}_ok"] = d.get("n", 0) > 0
            for m in METRICS:
                row[f"{ab}_{m}"] = d.get(m)
        rows.append(row)
    return rows


def bootstrap_ci(diffs, B=10_000, seed=42, alpha=0.05):
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(B):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int((alpha / 2) * B)]
    hi = means[int((1 - alpha / 2) * B) - 1]
    return lo, hi


def summarise(rows):
    out = []
    for ab in ABLATIONS:
        for metric in METRICS:
            paired = [
                (r[f"full_{metric}"], r[f"{ab}_{metric}"])
                for r in rows
                if r.get(f"{ab}_ok") and r[f"full_{metric}"] is not None
                and r[f"{ab}_{metric}"] is not None
            ]
            n = len(paired)
            if n < 2:
                continue
            diffs = [b - a for a, b in paired]  # ablation - full
            mean_diff = sum(diffs) / n
            sd = statistics.stdev(diffs)
            lo, hi = bootstrap_ci(diffs)
            out.append(
                {
                    "ablation": ab,
                    "metric": metric,
                    "n_sessions": n,
                    "mean_diff(ab-Full)": round(mean_diff, 4),
                    "sd_diff": round(sd, 4),
                    "ci95_low": round(lo, 4),
                    "ci95_high": round(hi, 4),
                    "ci_excludes_zero": (lo > 0) or (hi < 0),
                }
            )
    return out


def main():
    rows = collect_paired()
    if not rows:
        raise SystemExit(f"No sessions found under: {SESSIONS_DIR}")
    summary = summarise(rows)
    out_csv = Path(__file__).with_name("offline_replay_paired_bootstrap.csv")
    keys = list(summary[0].keys()) if summary else []
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in summary:
            w.writerow(r)
    print(f"Sessions used: {len(rows)}")
    print(f"Wrote: {out_csv}")
    for r in summary:
        print(r)


if __name__ == "__main__":
    main()
