#!/usr/bin/env python3
"""7x7 cross-modal tables: visual emotion x text emotion (vader7 / lexicon / hf)."""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from cross_modal_consistency import EMOTIONS, iter_session_files, load_chat_history
from text_emotion_7 import label_turn

OUT = Path(__file__).parent


def write_matrix(counts: Counter, path: Path, row_label: str, col_label: str) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([row_label + "\\" + col_label] + list(EMOTIONS) + ["row_total"])
        for em_r in EMOTIONS:
            ns = [counts.get((em_r, em_c), 0) for em_c in EMOTIONS]
            w.writerow([em_r] + ns + [sum(ns)])
    print(f"Wrote {path}")


def summarize_mismatch(rows: list[dict], vis_key: str, txt_key: str) -> list[str]:
    n = 0
    exact = 0
    both_nn_mis = 0
    for r in rows:
        vis = r.get(vis_key, "")
        txt = r.get(txt_key, "")
        if not vis or not txt:
            continue
        n += 1
        if vis == txt:
            exact += 1
        if vis != "neutral" and txt != "neutral" and vis != txt:
            both_nn_mis += 1
    return [
        f"  {txt_key}: n={n} exact_match={exact} ({100*exact/max(n,1):.1f}%) "
        f"both_non_neutral_mismatch={both_nn_mis} ({100*both_nn_mis/max(n,1):.1f}%)"
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", default="vader7,lexicon")
    args = ap.parse_args()
    channels = {c.strip() for c in args.channels.split(",") if c.strip()}

    rows: list[dict] = []
    for sid, session_dir in iter_session_files():
        for i, msg in enumerate(load_chat_history(session_dir)):
            if msg.get("role") != "user":
                continue
            vis = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            if vis not in EMOTIONS:
                continue
            r = {"session_id": sid, "turn_index": i}
            r.update(label_turn(msg, channels))
            rows.append(r)

    lines = ["7x7 cross-modal summary (41 sessions)", "=" * 50, f"Turns: {len(rows)}", ""]
    for txt_col in [k for k in (rows[0].keys() if rows else []) if k.startswith("text7_")]:
        mat = Counter()
        for r in rows:
            vis = r.get("visual_emotion_7", "")
            txt = r.get(txt_col, "")
            if vis and txt:
                mat[(vis, txt)] += 1
        write_matrix(mat, OUT / f"cross_modal_7x7_{txt_col}.csv", "visual", txt_col)
        lines.extend(summarize_mismatch(rows, "visual_emotion_7", txt_col))

    (OUT / "cross_modal_7x7_summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
