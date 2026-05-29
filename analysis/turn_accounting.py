#!/usr/bin/env python3
"""Fast corpus turn accounting (user vs assistant, labelled vs dropped)."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

EMOTIONS = ["happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"]
SENTIMENTS = ["positive", "neutral", "negative"]
OUT = Path(__file__).parent / "turn_accounting.csv"
OUT_SUMMARY = Path(__file__).parent / "turn_accounting_summary.txt"


def load_messages(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("messages", [])
    return data if isinstance(data, list) else []


def has_affect(msg: dict) -> bool:
    em = str(msg.get("emotion") or msg.get("emotion_visual") or "").lower().strip()
    sn = str(msg.get("sentiment", "")).lower().strip()
    return em in EMOTIONS and sn in SENTIMENTS


def discover_sessions() -> list[tuple[str, str, Path]]:
    """Return (bundle_name, session_id, chat_path) for all percy_data sessions."""
    from merci_session_discovery import iter_all_sessions

    rows: list[tuple[str, str, Path]] = []
    for sid, path in iter_all_sessions(include_numeric=True):
        bundle = "numeric" if sid.isdigit() else "fixed_data"
        rows.append((bundle, sid, path))
    return rows


def count_session(messages: list[dict]) -> Counter:
    c: Counter = Counter()
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        c[f"{role}_all"] += 1
        if has_affect(msg):
            c[f"{role}_labelled"] += 1
        else:
            c[f"{role}_unlabelled"] += 1
    return c


def main() -> None:
    sessions = discover_sessions()
    per_bundle: Counter = Counter()
    totals = Counter()
    rows: list[dict] = []

    for bundle, sid, path in sessions:
        c = count_session(load_messages(path))
        per_bundle[f"{bundle}_sessions"] += 1
        row = {
            "bundle": bundle,
            "session_id": sid,
            "chat_file": path.name,
            "user_messages": c["user_all"],
            "assistant_messages": c["assistant_all"],
            "dialogue_messages": c["user_all"] + c["assistant_all"],
            "user_labelled": c["user_labelled"],
            "assistant_labelled": c["assistant_labelled"],
            "user_unlabelled": c["user_unlabelled"],
            "assistant_unlabelled": c["assistant_unlabelled"],
        }
        rows.append(row)
        for k, v in c.items():
            totals[k] += v

    user_all = totals["user_all"]
    asst_all = totals["assistant_all"]
    dialogue = user_all + asst_all
    user_lab = totals["user_labelled"]
    asst_lab = totals["assistant_labelled"]

    lines = [
        "MERCI turn accounting",
        "=" * 50,
        f"Unique sessions: {len(sessions)}",
        "",
        "Dialogue messages in scanned JSON (user + assistant roles):",
        f"  User messages:        {user_all}",
        f"  Assistant messages:   {asst_all}",
        f"  Total dialogue msgs:  {dialogue}",
    ]
    if asst_all:
        lines.append(f"  User/assistant ratio: {user_all / asst_all:.3f}")
    lines += [
        "",
        "Affect labels (emotion + sentiment fields present):",
        f"  User labelled:        {user_lab} ({100 * user_lab / max(user_all, 1):.1f}% of user msgs)",
        f"  User unlabelled:      {totals['user_unlabelled']}",
        f"  Assistant labelled:   {asst_lab} ({100 * asst_lab / max(asst_all, 1):.1f}% of assistant msgs)",
        f"  Assistant unlabelled: {totals['assistant_unlabelled']}",
        "",
        "Interpretation for the paper:",
        "  - Full release: 30 participants, ~12.5 h AV (see CBMI cite; no global turn total here).",
        "  - Cross-modal Section 5 uses USER turns only (participant affect).",
        "  - Assistant JSON usually lacks emotion/sentiment -> not in 7x3 audit.",
        f"  - Replicated bundle user msgs here: {user_all} (30 sessions under percy_data/).",
        f"  - cross_modal_consistency.py: {user_lab} user turns with valid labels (30 sessions).",
    ]

    fieldnames = list(rows[0].keys())
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
        w.writerow(
            {
                "bundle": "ALL",
                "session_id": "TOTAL",
                "chat_file": "",
                "user_messages": user_all,
                "assistant_messages": asst_all,
                "dialogue_messages": dialogue,
                "user_labelled": user_lab,
                "assistant_labelled": asst_lab,
                "user_unlabelled": totals["user_unlabelled"],
                "assistant_unlabelled": totals["assistant_unlabelled"],
            }
        )

    OUT_SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
