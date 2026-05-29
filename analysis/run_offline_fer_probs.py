#!/usr/bin/env python3
"""Offline replay of PERCY MobileNetV2 FER on normalized session videos.

For each audited user turn, sample frames in [t_start_sec, t_end_sec] from
whole_video.mp4, run face detection + emotion classifier, and export 7-dim
softmax probabilities (same label order as deployment).

Requires PERCY emotion_model deps (torch, cv2, basetrainer). Run inside the
ROS1 Docker image after install_emotion_model_deps.sh, e.g.:

  cd /workspace/PERCY/src/emotion_model
  python3 /workspace/paper_writing/Paper_writing/Claude_Writing/analysis/run_offline_fer_probs.py
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np

from merci_message_io import EMOTIONS
from merci_normalized_media import iter_normalized_sessions, load_session_messages

OUT_DIR = Path(__file__).parent
DEFAULT_PERCY_EMOTION = Path(__file__).resolve().parents[4] / "PERCY" / "src" / "emotion_model"
FER_EMOTIONS = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]


def _load_predictor(percy_emotion_dir: Path, device: str):
    os.chdir(percy_emotion_dir)
    for p in (str(percy_emotion_dir), str(percy_emotion_dir / "libs")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import argparse as ap

    from basetrainer.utils import setup_config
    from demo import Predictor

    parser = ap.ArgumentParser()
    parser.add_argument("-c", "--config_file", default="configs/config.yaml", type=str)
    parser.add_argument(
        "-m",
        "--model_file",
        default=(
            "data/pretrained/mobilenet_v2_1.0_CrossEntropyLoss_20230313090258/"
            "model/latest_model_099_94.7200.pth"
        ),
        type=str,
    )
    parser.add_argument("--device", default=device, type=str)
    parser.add_argument("--image_dir", default="data/test_image", type=str)
    parser.add_argument("--video_file", default=None, type=str)
    parser.add_argument("--out_dir", default="output", type=str)
    args = parser.parse_args([])
    cfg = setup_config.parser_config(args, cfg_updata=False)
    cfg.device = device
    return Predictor(cfg)


def _face_prob_vector(predictor, rgb_image: np.ndarray) -> np.ndarray | None:
    import torch

    faces, _dets = predictor.detect_face(rgb_image)
    if len(faces) == 0:
        return None
    input_tensor = predictor.pre_process(faces)
    output = predictor.forward(input_tensor)
    prob_scores = predictor.softmax(np.asarray(output.cpu()), axis=1)
    if prob_scores.shape[0] == 1:
        vec = prob_scores[0]
    else:
        vec = prob_scores.mean(axis=0)
    return np.asarray(vec, dtype=np.float64)


def _sample_times(t0: float, t1: float, n: int) -> list[float]:
    if t1 <= t0:
        return [float(t0)]
    if n <= 1:
        return [0.5 * (t0 + t1)]
    fracs = np.linspace(0.25, 0.75, n)
    return [float(t0 + f * (t1 - t0)) for f in fracs]


def _read_frame_at_sec(cap, t_sec: float, fps: float) -> np.ndarray | None:
    import cv2

    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t_sec) * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        idx = int(max(0.0, t_sec) * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def _neutral_prob() -> np.ndarray:
    v = np.zeros(len(FER_EMOTIONS), dtype=np.float64)
    v[FER_EMOTIONS.index("neutral")] = 1.0
    return v


def _audited_sessions() -> set[str]:
    audited_csv = OUT_DIR / "cross_modal_per_session.csv"
    if not audited_csv.exists():
        return set()
    with audited_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {str(r.get("session_id", "")).strip() for r in reader if r.get("session_id")}


def run_export(
    *,
    percy_emotion_dir: Path,
    device: str,
    samples_per_turn: int,
    max_sessions: int | None,
) -> list[dict]:
    import cv2

    predictor = _load_predictor(percy_emotion_dir, device)
    audited = _audited_sessions()
    rows: list[dict] = []
    n_sessions = 0

    for sid, session_dir in iter_normalized_sessions():
        if audited and sid not in audited:
            continue
        video_path = session_dir / "whole_video.mp4"
        if not video_path.exists():
            continue
        n_sessions += 1
        if max_sessions is not None and n_sessions > max_sessions:
            break

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            continue
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)

        messages = load_session_messages(session_dir)
        for msg in messages:
            if msg.get("role") != "user":
                continue
            try:
                t0 = float(msg.get("t_start_sec", msg.get("asr_start")))
                t1 = float(msg.get("t_end_sec", msg.get("asr_end")))
            except (TypeError, ValueError):
                continue
            text = str(msg.get("content") or "").strip()
            em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            if em not in EMOTIONS or not text:
                continue

            probs_acc: list[np.ndarray] = []
            for t in _sample_times(t0, t1, samples_per_turn):
                rgb = _read_frame_at_sec(cap, t, fps)
                if rgb is None:
                    continue
                vec = _face_prob_vector(predictor, rgb)
                if vec is not None:
                    probs_acc.append(vec)

            if probs_acc:
                mean_prob = np.mean(np.vstack(probs_acc), axis=0)
                mean_prob = mean_prob / max(mean_prob.sum(), 1e-12)
            else:
                mean_prob = _neutral_prob()

            midx = msg.get("message_index")
            try:
                midx_i = int(midx) if midx is not None else -1
            except (TypeError, ValueError):
                midx_i = -1

            row = {
                "session_id": sid,
                "message_index": midx_i,
                "t_start_sec": t0,
                "t_end_sec": t1,
                "emotion_visual_deployed": em,
                "n_frames_with_face": len(probs_acc),
            }
            for i, label in enumerate(FER_EMOTIONS):
                row[f"fer_p_{label}"] = float(mean_prob[i])
            rows.append(row)

        cap.release()

    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Export offline FER 7-dim probabilities for MERCI turns.")
    ap.add_argument(
        "--percy-emotion-dir",
        type=Path,
        default=Path(os.environ.get("PERCY_EMOTION_MODEL_DIR", DEFAULT_PERCY_EMOTION)),
    )
    ap.add_argument("--device", default=os.environ.get("FER_DEVICE", "cpu"))
    ap.add_argument("--samples-per-turn", type=int, default=3)
    ap.add_argument("--max-sessions", type=int, default=None, help="smoke test limit")
    ap.add_argument(
        "--out-csv",
        type=Path,
        default=OUT_DIR / "offline_fer_probs.csv",
    )
    args = ap.parse_args()

    rows = run_export(
        percy_emotion_dir=args.percy_emotion_dir.resolve(),
        device=args.device,
        samples_per_turn=max(1, args.samples_per_turn),
        max_sessions=args.max_sessions,
    )
    if not rows:
        raise SystemExit("No rows exported; check normalized_media paths and audited sessions.")

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with args.out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    n_face = sum(1 for r in rows if int(r.get("n_frames_with_face", 0)) > 0)
    print(f"Wrote {len(rows)} rows to {args.out_csv} ({n_face} turns with >=1 face frame)")


if __name__ == "__main__":
    main()
