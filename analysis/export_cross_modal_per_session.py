#!/usr/bin/env python3
"""Export per-session valence-conflict counts (numeric folders only).

For the full 30-session MERCI corpus (fixed_data + 100–104), use instead::

    cd analysis && python3 cross_modal_consistency.py

That writes ``cross_modal_per_session.csv`` with all sessions. Then::

    python3 plot_merci_figures.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

VISUAL_POSITIVE = {"happy"}
VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}


def valence_conflict(visual: str, sentiment: str) -> bool:
    visual = (visual or "").strip().lower()
    sentiment = (sentiment or "").strip().lower()
    if visual == "neutral" or sentiment == "neutral":
        return False
    if visual in VISUAL_POSITIVE and sentiment == "negative":
        return True
    if visual in VISUAL_NEGATIVE and sentiment == "positive":
        return True
    return False


def session_stats(chat_path: Path) -> tuple[int, int] | None:
    data = json.loads(chat_path.read_text(encoding="utf-8"))
    n_turns = n_conflict = 0
    for msg in data:
        if msg.get("role") != "user":
            continue
        visual = msg.get("emotion_visual")
        sentiment = msg.get("sentiment")
        if not visual or not sentiment:
            continue
        n_turns += 1
        flagged = msg.get("cross_modal_valence_conflict")
        if flagged is None:
            flagged = valence_conflict(visual, sentiment)
        if flagged:
            n_conflict += 1
    if n_turns == 0:
        return None
    return n_turns, n_conflict


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "data_root",
        type=Path,
        help="Directory with one subfolder per session (each containing chat_history.json)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "cross_modal_per_session.csv",
    )
    parser.add_argument(
        "--min-turns",
        type=int,
        default=10,
        help="Only include sessions with at least this many labelled user turns",
    )
    args = parser.parse_args()

    rows = []
    for session_dir in sorted(args.data_root.iterdir()):
        if not session_dir.is_dir():
            continue
        chat = session_dir / "chat_history.json"
        if not chat.exists():
            continue
        stats = session_stats(chat)
        if stats is None:
            continue
        n_turns, n_conflict = stats
        if n_turns < args.min_turns:
            continue
        rows.append(
            {
                "session_id": session_dir.name,
                "n_turns": n_turns,
                "conflict_n": n_conflict,
                "conflict_rate_pct": round(100.0 * n_conflict / n_turns, 2),
            }
        )

    if not rows:
        raise SystemExit(f"No sessions found under {args.data_root}")

    out = pd.DataFrame(rows).sort_values("session_id")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output, index=False)
    print(f"Wrote {len(out)} sessions to {args.output}")
    print(f"Total: {out['conflict_n'].sum()} conflicts / {out['n_turns'].sum()} turns")


if __name__ == "__main__":
    main()
