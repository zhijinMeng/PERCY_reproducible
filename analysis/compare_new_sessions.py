#!/usr/bin/env python3
"""Compare new _待处理 sessions (100-104) vs existing 25-session bundle."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[3] / "fixed_data" / "Ari Robot"
NEW = ROOT / "_待处理"
OLD_BUCKETS = [
    ROOT / "_已处理" / "_无音轨mp4",
    ROOT / "_已处理" / "_含音轨mp4",
]
EMOTIONS = {"happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"}
SENTIMENTS = {"positive", "neutral", "negative"}
CHAT_PRIORITY = (
    "chat_history_asr_aligned_large_v3.json",
    "chat_history_aligned.json",
    "chat_history.json",
)


def load_messages(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("messages", [])
    return data if isinstance(data, list) else []


def scan_session(session_dir: Path) -> dict:
    files = sorted(f.name for f in session_dir.iterdir() if f.is_file())
    chat_path = None
    for name in CHAT_PRIORITY:
        if name in files:
            chat_path = session_dir / name
            break
    msgs = load_messages(chat_path) if chat_path else []
    counts: Counter = Counter()
    user_emotions: Counter = Counter()
    user_missing = Counter()
    for msg in msgs:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        counts[f"{role}_all"] += 1
        em = str(msg.get("emotion") or msg.get("emotion_visual") or "").lower().strip()
        sn = str(msg.get("sentiment", "")).lower().strip()
        if em in EMOTIONS and sn in SENTIMENTS:
            counts[f"{role}_labelled"] += 1
        if (
            msg.get("asr_start") is not None
            or msg.get("asr_end") is not None
            or msg.get("t_start_sec") is not None
            or msg.get("t_end_sec") is not None
        ):
            counts[f"{role}_asr_ts"] += 1
        if role == "user":
            if em in EMOTIONS:
                user_emotions[em] += 1
            else:
                user_missing["emotion_or_visual"] += 1
            if sn not in SENTIMENTS:
                user_missing["sentiment"] += 1
    meta = {}
    meta_path = session_dir / "recording_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # duplicate-turn detection (same turn index + role)
    turn_role_counts: Counter = Counter()
    for msg in msgs:
        if msg.get("role") in ("user", "assistant"):
            turn_role_counts[(msg.get("turn"), msg.get("role"))] += 1
    dup_pairs = sum(1 for _, n in turn_role_counts.items() if n > 1)

    return {
        "files": files,
        "dup_turn_role_pairs": dup_pairs,
        "schema_emotion_field": (
            "emotion_visual"
            if any("emotion_visual" in m for m in msgs if m.get("role") == "user")
            else "emotion"
            if any("emotion" in m for m in msgs if m.get("role") == "user")
            else "none"
        ),
        "schema_time_field": (
            "t_start_sec"
            if any("t_start_sec" in m for m in msgs)
            else "asr_start"
            if any("asr_start" in m for m in msgs)
            else "none"
        ),
        "chat_file": chat_path.name if chat_path else None,
        "counts": dict(counts),
        "user_emotions": dict(user_emotions),
        "user_missing": dict(user_missing),
        "has_finalize": "finalize.done" in files,
        "has_pre_survey": "pre_survey.json" in files,
        "has_profile": "profile.json" in files,
        "has_timeline": "dialogue_timeline.json" in files,
        "has_asr_aligned": "chat_history_asr_aligned_large_v3.json" in files,
        "recording_meta": meta,
    }


def discover_old_sessions() -> list[Path]:
    seen: dict[str, Path] = {}
    for bucket in OLD_BUCKETS:
        if not bucket.exists():
            continue
        for d in sorted(bucket.iterdir()):
            if not d.is_dir():
                continue
            if (d / "chat_history_asr_aligned_large_v3.json").exists():
                seen[d.name] = d
    return [seen[k] for k in sorted(seen)]


def stats(vals: list[float | int]) -> str:
    if not vals:
        return "n/a"
    return f"min={min(vals)} avg={mean(vals):.1f} max={max(vals)}"


def main() -> None:
    print("MERCI new-session check (100-104 vs 25-session baseline)")
    print("=" * 60)

    new_ids = ["100", "101", "102", "103", "104"]
    new_rows: list[tuple[str, dict]] = []
    print("\n--- NEW (pending) ---")
    for sid in new_ids:
        p = NEW / sid
        if not p.exists():
            print(f"{sid}: MISSING folder")
            continue
        r = scan_session(p)
        new_rows.append((sid, r))
        c = r["counts"]
        print(f"\n{sid}:")
        print(f"  chat: {r['chat_file']}")
        print(f"  files: {', '.join(r['files'])}")
        print(
            f"  turns: user={c.get('user_all', 0)} asst={c.get('assistant_all', 0)} "
            f"user_labelled={c.get('user_labelled', 0)} user_asr_ts={c.get('user_asr_ts', 0)}"
        )
        print(
            f"  flags: finalize={r['has_finalize']} profile={r['has_profile']} "
            f"asr_aligned_v3={r['has_asr_aligned']}"
        )
        if r["user_emotions"]:
            print(f"  user emotions: {r['user_emotions']}")
        if r["user_missing"]:
            print(f"  user missing: {r['user_missing']}")
        print(
            f"  schema: emotion={r['schema_emotion_field']} time={r['schema_time_field']} "
            f"dup_turn_role_pairs={r['dup_turn_role_pairs']}"
        )
        if r["recording_meta"]:
            keys = list(r["recording_meta"].keys())[:8]
            print(f"  recording_meta keys (sample): {keys}")

    old_dirs = discover_old_sessions()
    print(f"\n--- OLD baseline (chat_history_asr_aligned_large_v3.json) ---")
    print(f"Sessions: {len(old_dirs)}")
    old_scans = [scan_session(d) for d in old_dirs]
    for key in ("user_all", "assistant_all", "user_labelled", "user_asr_ts"):
        vals = [s["counts"].get(key, 0) for s in old_scans]
        print(f"  {key}: {stats(vals)}")

    print("\n--- NEW vs OLD ---")
    new_scans = [r for _, r in new_rows]
    for key in ("user_all", "assistant_all", "user_labelled", "user_asr_ts"):
        nvals = [s["counts"].get(key, 0) for s in new_scans]
        ovals = [s["counts"].get(key, 0) for s in old_scans]
        print(f"  {key}: NEW={nvals} | OLD {stats(ovals)}")

    # cross-modal preview on chat_history.json (new) vs v3 (old)
    print("\n--- Cross-modal preview (same rules as cross_modal_consistency.py) ---")

    def conflict_rate(msgs: list[dict]) -> tuple[int, int, float]:
        kept = 0
        conflict = 0
        for msg in msgs:
            if msg.get("role") != "user":
                continue
            em = str(msg.get("emotion") or msg.get("emotion_visual") or "").lower().strip()
            sn = str(msg.get("sentiment", "")).lower().strip()
            if em not in EMOTIONS or sn not in SENTIMENTS:
                continue
            kept += 1
            if em == "neutral" or sn == "neutral":
                continue
            pos_v = em == "happy"
            neg_v = em in {"sad", "angry", "disgust", "fear"}
            if (pos_v and sn == "negative") or (neg_v and sn == "positive"):
                conflict += 1
        rate = 100.0 * conflict / kept if kept else 0.0
        return kept, conflict, rate

    for sid, r in new_rows:
        p = NEW / sid / (r["chat_file"] or "chat_history.json")
        if p.exists():
            k, c, rate = conflict_rate(load_messages(p))
            print(f"  NEW {sid}: kept={k} conflict={c} ({rate:.1f}%)")

    old_rates = []
    for d in old_dirs:
        p = d / "chat_history_asr_aligned_large_v3.json"
        k, c, rate = conflict_rate(load_messages(p))
        old_rates.append(rate)
        if k:
            pass
    print(f"  OLD 25 sessions: conflict% {stats(old_rates)}")

    out = Path(__file__).parent / "new_sessions_comparison.csv"
    import csv

    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "cohort",
                "session_id",
                "chat_file",
                "user_all",
                "assistant_all",
                "user_labelled",
                "user_asr_ts",
                "has_asr_aligned_v3",
                "has_finalize",
            ],
        )
        w.writeheader()
        for sid, r in new_rows:
            c = r["counts"]
            w.writerow(
                {
                    "cohort": "new",
                    "session_id": sid,
                    "chat_file": r["chat_file"],
                    "user_all": c.get("user_all", 0),
                    "assistant_all": c.get("assistant_all", 0),
                    "user_labelled": c.get("user_labelled", 0),
                    "user_asr_ts": c.get("user_asr_ts", 0),
                    "has_asr_aligned_v3": r["has_asr_aligned"],
                    "has_finalize": r["has_finalize"],
                }
            )
        for d, s in zip(old_dirs, old_scans):
            c = s["counts"]
            w.writerow(
                {
                    "cohort": "old",
                    "session_id": d.name,
                    "chat_file": s["chat_file"],
                    "user_all": c.get("user_all", 0),
                    "assistant_all": c.get("assistant_all", 0),
                    "user_labelled": c.get("user_labelled", 0),
                    "user_asr_ts": c.get("user_asr_ts", 0),
                    "has_asr_aligned_v3": s["has_asr_aligned"],
                    "has_finalize": s["has_finalize"],
                }
            )
    print("\n--- Duration / pipeline ---")
    for sid, r in new_rows:
        p = NEW / sid
        meta = json.loads((p / "recording_meta.json").read_text(encoding="utf-8"))
        bm = json.loads((p / "benchmark_manifest.json").read_text(encoding="utf-8"))
        msgs = load_messages(p / (r["chat_file"] or "chat_history.json"))
        user_ends = [m["t_end_sec"] for m in msgs if m.get("role") == "user" and m.get("t_end_sec") is not None]
        dial_span = max(user_ends) - min(user_ends) if user_ends else 0
        utt_dir = p / "utterances"
        utt_n = len(list(utt_dir.glob("user_*.wav"))) if utt_dir.exists() else 0
        pairs = [(m.get("turn"), m.get("role")) for m in msgs if m.get("role") in ("user", "assistant")]
        dup = len(pairs) - len(set(pairs))
        conflicts = sum(1 for m in msgs if m.get("role") == "user" and m.get("cross_modal_valence_conflict"))
        print(
            f"  {sid}: video={meta.get('video_duration_sec', 0):.0f}s "
            f"dial_span={dial_span:.0f}s utt_wavs={utt_n} dup={dup} "
            f"conflict_flags={conflicts} whisper={bm.get('files', {}).get('whisper_asr')}"
        )

    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
