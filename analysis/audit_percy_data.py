#!/usr/bin/env python3
"""Full audit of Research/percy_data for paper statistics."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from percy_data_root import FIXED_DATA_ARI, PERCY_DATA_ROOT

EMOTIONS = ["happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"]
SENTIMENTS = ["positive", "neutral", "negative"]
VISUAL_POSITIVE = {"happy"}
VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}

CHAT_NAMES = (
    "chat_history_asr_aligned_large_v3.json",
    "chat_history_aligned.json",
    "chat_history.json",
)


def pick_chat(session_dir: Path) -> Path | None:
    for name in CHAT_NAMES:
        p = session_dir / name
        if p.exists():
            return p
    return None


def load_messages(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("messages", [])
    return data if isinstance(data, list) else []


def classify_turn(emotion: str, sentiment: str) -> str:
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


def discover_fixed_data_sessions() -> dict[str, Path]:
    seen: dict[str, Path] = {}
    if not FIXED_DATA_ARI.exists():
        return seen
    preferred = ["_人工修订", "_含音轨mp4", "_无音轨mp4"]
    pending = FIXED_DATA_ARI / "_待处理"
    if pending.exists():
        for d in sorted(pending.iterdir()):
            if d.is_dir() and (p := pick_chat(d)):
                seen[d.name] = p
    processed = FIXED_DATA_ARI / "_已处理"
    for bucket in preferred:
        bdir = processed / bucket if processed.exists() else FIXED_DATA_ARI / bucket
        if not bdir.exists():
            continue
        for d in bdir.iterdir():
            if d.is_dir() and d.name not in seen and (p := pick_chat(d)):
                seen[d.name] = p
    return seen


def discover_numeric_sessions() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for d in sorted(PERCY_DATA_ROOT.iterdir()):
        if not d.is_dir() or not d.name.isdigit():
            continue
        if p := pick_chat(d):
            found[d.name] = p
    return found


def audit_messages(messages: list[dict], session_id: str) -> dict:
    user_all = user_labelled = asst_all = 0
    dropped = 0
    classes = Counter()
    cells = Counter()
    lat_scanned = lat_clean = lat_excluded = 0
    clean_gaps: list[float] = []
    prev_user = None

    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "user":
            user_all += 1
            em = str(msg.get("emotion") or msg.get("emotion_visual") or "").lower().strip()
            sn = str(msg.get("sentiment", "")).lower().strip()
            if em in EMOTIONS and sn in SENTIMENTS:
                user_labelled += 1
                classes[classify_turn(em, sn)] += 1
                cells[(em, sn)] += 1
            else:
                dropped += 1
            prev_user = msg
        elif role == "assistant":
            asst_all += 1
            if prev_user is not None:
                ue = prev_user.get("asr_end") or prev_user.get("t_end_sec")
                a_start = msg.get("asr_start") or msg.get("t_start_sec")
                if ue is not None and a_start is not None:
                    lat_scanned += 1
                    dt = float(a_start) - float(ue)
                    if dt < 0 or dt > 60:
                        lat_excluded += 1
                    else:
                        lat_clean += 1
                        clean_gaps.append(dt)
                prev_user = None

    return {
        "session_id": session_id,
        "user_all": user_all,
        "user_labelled": user_labelled,
        "user_dropped": dropped,
        "assistant_all": asst_all,
        "dialogue": user_all + asst_all,
        "classes": classes,
        "cells": cells,
        "lat_scanned": lat_scanned,
        "lat_clean": lat_clean,
        "lat_excluded": lat_excluded,
        "clean_gaps": clean_gaps,
    }


def main() -> None:
    fixed = discover_fixed_data_sessions()
    numeric = discover_numeric_sessions()

    print("=" * 60)
    print(f"PERCY_DATA_ROOT: {PERCY_DATA_ROOT}")
    print(f"fixed_data sessions (chat json): {len(fixed)}")
    print(f"numeric folders (100-104 etc):   {len(numeric)}")
    print()

    # Aggregate fixed_data (canonical for paper)
    totals = Counter()
    all_classes = Counter()
    all_cells = Counter()
    all_gaps: list[float] = []
    lat_scanned = lat_excluded = 0
    per_session_conflict: list[tuple[str, float, int]] = []

    for sid, path in sorted(fixed.items()):
        r = audit_messages(load_messages(path), sid)
        totals["sessions"] += 1
        totals["user_all"] += r["user_all"]
        totals["user_labelled"] += r["user_labelled"]
        totals["user_dropped"] += r["user_dropped"]
        totals["assistant_all"] += r["assistant_all"]
        totals["dialogue"] += r["dialogue"]
        all_classes.update(r["classes"])
        all_cells.update(r["cells"])
        all_gaps.extend(r["clean_gaps"])
        lat_scanned += r["lat_scanned"]
        lat_excluded += r["lat_excluded"]
        n = r["user_labelled"]
        if n:
            cr = 100.0 * r["classes"].get("conflict", 0) / n
            per_session_conflict.append((sid, cr, n))

    n_lab = totals["user_labelled"]
    n_conf = all_classes.get("conflict", 0)
    print("--- fixed_data/Ari Robot (paper canonical) ---")
    print(f"Sessions:              {totals['sessions']}")
    print(f"User messages (all):   {totals['user_all']}")
    print(f"User labelled (audit): {n_lab}")
    print(f"User dropped:          {totals['user_dropped']}")
    print(f"Assistant messages:    {totals['assistant_all']}")
    print(f"Dialogue messages:     {totals['dialogue']}")
    print()
    print("Cross-modal classes (labelled user turns):")
    for k in ("consistent", "neutral", "conflict", "other"):
        v = all_classes.get(k, 0)
        pct = 100.0 * v / n_lab if n_lab else 0
        print(f"  {k:12s}: {v:4d}  ({pct:.1f}%)")
    print(f"  conflict rate: {100.0*n_conf/n_lab:.1f}%" if n_lab else "")
    print()
    print("Latency pairs:")
    print(f"  scanned:   {lat_scanned}")
    print(f"  excluded:  {lat_excluded}")
    print(f"  clean:     {len(all_gaps)}")
    if all_gaps:
        print(f"  median:    {statistics.median(all_gaps):.2f} s")
        q = statistics.quantiles(all_gaps, n=4)
        print(f"  IQR:       [{q[0]:.2f}, {q[2]:.2f}] s")
    print()

    rates = [x[1] for x in per_session_conflict if x[2] >= 10]
    if rates:
        rs = sorted(rates)
        med = statistics.median(rs)
        q = statistics.quantiles(rs, n=4) if len(rs) >= 4 else (min(rs), max(rs))
        print(f"Per-session conflict (sessions with >=10 turns): n={len(rs)}")
        print(f"  median={med:.1f}%, IQR=[{q[0]:.1f}, {q[2]:.1f}]%, max={max(rs):.1f}%")

    print()
    print("7x3 confusion (labelled turns):")
    for em in EMOTIONS:
        ns = [all_cells.get((em, s), 0) for s in SENTIMENTS]
        print(f"  {em:10s} pos={ns[0]:4d} neu={ns[1]:4d} neg={ns[2]:4d}  total={sum(ns):4d}")

    if numeric:
        print()
        print("--- numeric session folders (benchmark re-record) ---")
        for sid, path in sorted(numeric.items()):
            r = audit_messages(load_messages(path), sid)
            print(
                f"  {sid}: user={r['user_all']} labelled={r['user_labelled']} "
                f"conflict={r['classes'].get('conflict',0)} "
                f"file={path.name}"
            )


if __name__ == "__main__":
    main()
