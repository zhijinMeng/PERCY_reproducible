"""Compute robot response latency from MERCI chat_history JSON files.

Latency = assistant_turn.asr_start - previous_user_turn.asr_end

Outputs:
  analysis/response_latency.csv
  analysis/response_latency_summary.csv
  analysis/asr_exclusions_by_session.csv
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from merci_session_discovery import iter_all_sessions

OUT_DIR = Path(__file__).parent


def collect_latencies() -> tuple[list[dict], dict[str, list[float]]]:
    per_turn: list[dict] = []
    per_session: dict[str, list[float]] = defaultdict(list)
    exclusions_by_session: dict[str, dict[str, int]] = defaultdict(
        lambda: {"scanned": 0, "excluded_negative": 0, "excluded_over60": 0, "clean": 0}
    )

    for session_id, chat_p in iter_all_sessions():
        with chat_p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            messages = data
        elif isinstance(data, dict):
            messages = data.get("messages", [])
        else:
            messages = []
        for msg in messages:
            if msg.get("asr_start") is None and msg.get("t_start_sec") is not None:
                msg["asr_start"] = msg["t_start_sec"]
            if msg.get("asr_end") is None and msg.get("t_end_sec") is not None:
                msg["asr_end"] = msg["t_end_sec"]
        prev_user = None
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "user":
                prev_user = msg
            elif role == "assistant" and prev_user is not None:
                ue = prev_user.get("asr_end")
                a_start = msg.get("asr_start")
                if ue is None or a_start is None:
                    prev_user = None
                    continue
                latency = float(a_start) - float(ue)
                ex = exclusions_by_session[session_id]
                ex["scanned"] += 1
                if latency < 0:
                    ex["excluded_negative"] += 1
                    filtered, reason = True, "negative_dt"
                elif latency > 60:
                    ex["excluded_over60"] += 1
                    filtered, reason = True, "over_60s"
                else:
                    ex["clean"] += 1
                    filtered, reason = False, "ok"
                per_turn.append({
                    "session": session_id,
                    "idx": i,
                    "latency_s": round(latency, 3),
                    "filtered": filtered,
                    "filter_reason": reason,
                    "match_note_user": prev_user.get("match_note", ""),
                    "match_note_assistant": msg.get("match_note", ""),
                })
                if not filtered:
                    per_session[session_id].append(latency)
                prev_user = None

    return per_turn, dict(per_session), dict(exclusions_by_session)


def summarise(per_session: dict[str, list[float]]) -> tuple[list[dict], dict]:
    rows = []
    all_vals: list[float] = []
    for sess, vals in per_session.items():
        all_vals.extend(vals)
        rows.append({
            "session": sess,
            "n_turns": len(vals),
            "mean_s": round(statistics.mean(vals), 3),
            "median_s": round(statistics.median(vals), 3),
            "sd_s": round(statistics.stdev(vals), 3) if len(vals) >= 2 else 0.0,
            "min_s": round(min(vals), 3),
            "max_s": round(max(vals), 3),
        })
    overall = {
        "session": "ALL",
        "n_turns": len(all_vals),
        "mean_s": round(statistics.mean(all_vals), 3) if all_vals else 0.0,
        "median_s": round(statistics.median(all_vals), 3) if all_vals else 0.0,
        "sd_s": round(statistics.stdev(all_vals), 3) if len(all_vals) >= 2 else 0.0,
        "min_s": round(min(all_vals), 3) if all_vals else 0.0,
        "max_s": round(max(all_vals), 3) if all_vals else 0.0,
    }
    if all_vals:
        sorted_vals = sorted(all_vals)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4]
        q3 = sorted_vals[3 * n // 4]
        overall["q1_s"] = round(q1, 3)
        overall["q3_s"] = round(q3, 3)
        overall["iqr_s"] = round(q3 - q1, 3)
    return rows, overall


def main() -> None:
    per_turn, per_session, exclusions = collect_latencies()

    n_total = len(per_turn)
    n_filtered = sum(1 for r in per_turn if r["filtered"])
    n_clean = n_total - n_filtered
    print(f"Total user→assistant pairs scanned: {n_total}")
    print(f"  filtered (negative or >60s): {n_filtered}")
    print(f"  clean: {n_clean}")
    print(f"Sessions with >=1 valid latency: {len(per_session)}")

    rows, overall = summarise(per_session)

    print(f"\n=== Overall response latency (n={overall['n_turns']} clean pairs, "
          f"{len(per_session)} sessions) ===")
    print(f"  median = {overall['median_s']}s")
    print(f"  mean   = {overall['mean_s']}s  (sd {overall['sd_s']})")
    if "q1_s" in overall:
        print(f"  IQR    = [{overall['q1_s']}, {overall['q3_s']}] s  "
              f"(width {overall['iqr_s']})")
    print(f"  range  = [{overall['min_s']}, {overall['max_s']}] s")

    pt_csv = OUT_DIR / "response_latency.csv"
    with pt_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(per_turn[0].keys()))
        w.writeheader()
        for r in per_turn:
            w.writerow(r)
    print(f"Wrote: {pt_csv}")

    sum_csv = OUT_DIR / "response_latency_summary.csv"
    with sum_csv.open("w", newline="", encoding="utf-8") as f:
        keys = ["session", "n_turns", "mean_s", "median_s", "sd_s", "min_s", "max_s"]
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in sorted(rows, key=lambda x: x["session"]):
            w.writerow(r)
        w.writerow({k: overall.get(k, "") for k in keys})
    print(f"Wrote: {sum_csv}")

    ex_csv = OUT_DIR / "asr_exclusions_by_session.csv"
    with ex_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "session_id", "scanned", "excluded_negative",
                "excluded_over60", "excluded_total", "clean",
            ],
        )
        w.writeheader()
        for sid in sorted(exclusions):
            e = exclusions[sid]
            w.writerow({
                "session_id": sid,
                "scanned": e["scanned"],
                "excluded_negative": e["excluded_negative"],
                "excluded_over60": e["excluded_over60"],
                "excluded_total": e["excluded_negative"] + e["excluded_over60"],
                "clean": e["clean"],
            })
    print(f"Wrote: {ex_csv}")


if __name__ == "__main__":
    main()
