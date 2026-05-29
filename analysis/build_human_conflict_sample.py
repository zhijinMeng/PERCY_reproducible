#!/usr/bin/env python3
"""Build stratified sample for §4.1 human conflict validation.

Exports ``human_conflict_sample.csv`` with conflict + matched control turns.
Uses paper §3.2 valence rules (not runtime ``cross_modal_valence_conflict``).

Example::

    export PERCY_DATA_ROOT=/home/zhijinmeng/Research/HF_Data/percy_data
    cd analysis
    python3 build_human_conflict_sample.py --n-total 180 --seed 42
    python3 build_human_conflict_sample.py --extract-clips --clips-dir clips/
"""
from __future__ import annotations

import argparse
import csv
import random
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from merci_media_paths import clip_window, pick_video, session_dir_from_chat
from merci_message_io import EMOTIONS, SENTIMENTS, load_json_messages, normalize_messages
from merci_session_discovery import iter_all_sessions
from merci_valence_rules import classify_turn, valence_conflict

OUT_DIR = Path(__file__).resolve().parent
SAMPLE_FIELDS = [
    "turn_id",
    "stratum_auto",
    "auto_rule_pred",
    "turn_class",
    "session_id",
    "msg_index",
    "user_turn_number",
    "dialogue_turn",
    "transcript",
    "emotion_visual",
    "sentiment",
    "t_start_sec",
    "t_end_sec",
    "clip_start_sec",
    "clip_end_sec",
    "video_path",
    "chat_path",
    "wav_path",
]


@dataclass(frozen=True)
class TurnRow:
    turn_id: str
    stratum_auto: str
    auto_rule_pred: int
    turn_class: str
    session_id: str
    msg_index: int
    user_turn_number: int
    dialogue_turn: int | None
    transcript: str
    emotion_visual: str
    sentiment: str
    t_start_sec: float | None
    t_end_sec: float | None
    clip_start_sec: float | None
    clip_end_sec: float | None
    video_path: str | None
    chat_path: str
    wav_path: str | None

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in SAMPLE_FIELDS}


def iter_labelled_user_turns() -> list[TurnRow]:
    rows: list[TurnRow] = []
    for session_id, chat_path in iter_all_sessions(include_numeric=True):
        session_dir = session_dir_from_chat(chat_path)
        messages = normalize_messages(load_json_messages(chat_path))
        video = pick_video(session_dir)
        video_s = str(video) if video else ""
        user_n = 0
        for msg_index, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue
            user_n += 1
            em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            sn = str(msg.get("sentiment", "")).lower().strip()
            if em not in EMOTIONS or sn not in SENTIMENTS:
                continue
            turn_class = classify_turn(em, sn)
            auto = int(valence_conflict(em, sn))
            stratum = "conflict" if auto else turn_class
            t0 = msg.get("t_start_sec") or msg.get("asr_start")
            t1 = msg.get("t_end_sec") or msg.get("asr_end")
            window = clip_window(
                float(t0) if t0 is not None else None,
                float(t1) if t1 is not None else None,
            )
            clip_start, clip_end = window if window else (None, None)
            wav = msg.get("wav")
            dialogue_turn = msg.get("turn")
            try:
                dialogue_turn = int(dialogue_turn) if dialogue_turn is not None else None
            except (TypeError, ValueError):
                dialogue_turn = None
            turn_id = f"{session_id}__u{user_n:04d}"
            rows.append(
                TurnRow(
                    turn_id=turn_id,
                    stratum_auto=stratum,
                    auto_rule_pred=auto,
                    turn_class=turn_class,
                    session_id=session_id,
                    msg_index=msg_index,
                    user_turn_number=user_n,
                    dialogue_turn=dialogue_turn,
                    transcript=str(msg.get("content", "")).strip(),
                    emotion_visual=em,
                    sentiment=sn,
                    t_start_sec=float(t0) if t0 is not None else None,
                    t_end_sec=float(t1) if t1 is not None else None,
                    clip_start_sec=clip_start,
                    clip_end_sec=clip_end,
                    video_path=video_s or None,
                    chat_path=str(chat_path.resolve()),
                    wav_path=str(Path(wav).resolve()) if wav and Path(wav).exists() else None,
                )
            )
    return rows


def sample_controls(
    pool: list[TurnRow],
    n: int,
    *,
    rng: random.Random,
    session_ids: set[str],
    consistent_frac: float,
) -> list[TurnRow]:
    """Pick controls: prefer same sessions; mix consistent / neutral."""
    consistent = [r for r in pool if r.turn_class == "consistent"]
    neutral = [r for r in pool if r.turn_class == "neutral"]
    n_cons = int(round(n * consistent_frac))
    n_neu = n - n_cons

    def pick(candidates: list[TurnRow], k: int) -> list[TurnRow]:
        if k <= 0 or not candidates:
            return []
        by_session: dict[str, list[TurnRow]] = defaultdict(list)
        for r in candidates:
            by_session[r.session_id].append(r)
        chosen: list[TurnRow] = []
        used: set[str] = set()
        # one per conflict session first
        for sid in session_ids:
            opts = [r for r in by_session.get(sid, []) if r.turn_id not in used]
            if opts and len(chosen) < k:
                r = rng.choice(opts)
                chosen.append(r)
                used.add(r.turn_id)
        rest = [r for r in candidates if r.turn_id not in used]
        rng.shuffle(rest)
        for r in rest:
            if len(chosen) >= k:
                break
            chosen.append(r)
        return chosen[:k]

    return pick(consistent, n_cons) + pick(neutral, n_neu)


def build_sample(
    all_rows: list[TurnRow],
    *,
    n_total: int,
    n_conflict: int | None,
    seed: int,
    consistent_frac: float,
    require_video: bool,
) -> list[TurnRow]:
    rng = random.Random(seed)
    if require_video:
        all_rows = [r for r in all_rows if r.video_path]
    conflict_pool = [r for r in all_rows if r.turn_class == "conflict"]
    control_pool = [r for r in all_rows if r.turn_class in ("consistent", "neutral")]

    if not conflict_pool:
        raise SystemExit("No conflict turns found; check PERCY_DATA_ROOT and chat JSON.")

    if n_conflict is None:
        n_conflict = min(len(conflict_pool), n_total // 2)
    n_conflict = min(n_conflict, len(conflict_pool))
    n_control = min(len(control_pool), n_total - n_conflict)

    conflict_sample = (
        conflict_pool
        if n_conflict >= len(conflict_pool)
        else rng.sample(conflict_pool, n_conflict)
    )
    session_ids = {r.session_id for r in conflict_sample}
    control_sample = sample_controls(
        control_pool,
        n_control,
        rng=rng,
        session_ids=session_ids,
        consistent_frac=consistent_frac,
    )
    sample = conflict_sample + control_sample
    rng.shuffle(sample)
    return sample


def write_csv(path: Path, rows: list[TurnRow]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r.as_dict())


def extract_clips(rows: list[TurnRow], clips_dir: Path, ffmpeg: str) -> None:
    clips_dir.mkdir(parents=True, exist_ok=True)
    for r in rows:
        if not r.video_path or r.clip_start_sec is None or r.clip_end_sec is None:
            continue
        out = clips_dir / f"{r.turn_id}.mp4"
        if out.exists():
            continue
        duration = r.clip_end_sec - r.clip_start_sec
        cmd = [
            ffmpeg,
            "-y",
            "-ss",
            f"{r.clip_start_sec:.3f}",
            "-i",
            r.video_path,
            "-t",
            f"{duration:.3f}",
            "-c",
            "copy",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print(f"clip failed {r.turn_id}: {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=OUT_DIR / "human_conflict_sample.csv")
    parser.add_argument("--n-total", type=int, default=180)
    parser.add_argument("--n-conflict", type=int, default=None, help="default: n_total // 2")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--consistent-frac",
        type=float,
        default=0.5,
        help="fraction of controls from consistent stratum (rest neutral)",
    )
    parser.add_argument("--extract-clips", action="store_true")
    parser.add_argument("--clips-dir", type=Path, default=OUT_DIR / "human_conflict_clips")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument(
        "--require-video",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="drop turns with no mp4 (needed for §4.1 face+text annotation)",
    )
    parser.add_argument(
        "--write-annotation-template",
        type=Path,
        default=None,
        help="also write empty human_conflict_annotations.csv for annotators",
    )
    args = parser.parse_args()

    all_rows = iter_labelled_user_turns()
    sample = build_sample(
        all_rows,
        n_total=args.n_total,
        n_conflict=args.n_conflict,
        seed=args.seed,
        consistent_frac=args.consistent_frac,
        require_video=args.require_video,
    )
    write_csv(args.output, sample)

    n_auto_c = sum(r.auto_rule_pred for r in sample)
    by_class = defaultdict(int)
    for r in sample:
        by_class[r.turn_class] += 1
    sessions = len({r.session_id for r in sample})
    no_video = sum(1 for r in sample if not r.video_path)

    print(f"Wrote {args.output} ({len(sample)} turns)")
    print(f"  auto conflict: {n_auto_c}  control: {len(sample) - n_auto_c}")
    print(f"  turn_class counts: {dict(by_class)}")
    print(f"  sessions: {sessions}  missing video_path: {no_video}")

    if args.extract_clips:
        extract_clips(sample, args.clips_dir, args.ffmpeg)
        print(f"Clips under {args.clips_dir}")

    if args.write_annotation_template:
        ann_fields = [
            "turn_id",
            "session_id",
            "user_turn_number",
            "auto_rule_pred",
            "human_conflict",
            "annotator_id",
            "adjudicated",
            "notes",
        ]
        with args.write_annotation_template.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=ann_fields)
            w.writeheader()
            for r in sample:
                w.writerow(
                    {
                        "turn_id": r.turn_id,
                        "session_id": r.session_id,
                        "user_turn_number": r.user_turn_number,
                        "auto_rule_pred": r.auto_rule_pred,
                        "human_conflict": "",
                        "annotator_id": "",
                        "adjudicated": "",
                        "notes": "",
                    }
                )
        print(f"Wrote annotation template {args.write_annotation_template}")


if __name__ == "__main__":
    main()
