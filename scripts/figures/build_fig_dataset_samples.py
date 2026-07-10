#!/usr/bin/env python3
"""Build fig_dataset_samples.{pdf,png}: 2x2 quadrant gallery for Section 3.1."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT = Path("/home/zhijinmeng/Research/HF_Data/percy_data/merci_hf_upload")
OUT = Path(__file__).resolve().parent
TMP = OUT / "_build_tmp"
TMP.mkdir(exist_ok=True)

FIG4_CONFLICT_SESSION = "00_00_00_02_07_00_00"

# Manual overrides: (quadrant, slot_index) -> (session_id, message_index)
PINNED_TURNS: dict[tuple[str, int], tuple[str, int]] = {
    ("OTHER", 0): ("00_00_02_04_07_00_00", 18),
    ("OTHER", 1): ("03_00_00_02_08_00_00", 61),
}

# Top-left, top-right, bottom-left, bottom-right quadrants; 2 frontal picks each.
QUADRANT_SPECS: list[tuple[str, list]] = [
    (
        "CONSISTENT",
        [
            lambda r: r["emotion_visual"] == "happy" and r["sentiment"] == "positive",
            lambda r: r["emotion_visual"] == "disgust" and r["sentiment"] == "negative",
        ],
    ),
    (
        "NEUTRAL",
        [
            lambda r: r["emotion_visual"] == "neutral" and r["sentiment"] == "neutral",
            lambda r: r["emotion_visual"] == "neutral" and r["sentiment"] == "neutral",
        ],
    ),
    (
        "CONFLICT",
        [
            lambda r: r["emotion_visual"] == "disgust" and r["sentiment"] == "positive",
            lambda r: r["emotion_visual"] == "happy" and r["sentiment"] == "negative",
        ],
    ),
    (
        "OTHER",
        [
            lambda r: r["emotion_visual"] == "surprise" and r["sentiment"] == "positive",
            lambda r: r["emotion_visual"] == "surprise" and r["sentiment"] == "positive",
        ],
    ),
]

def frontal_score(img: Image.Image) -> float:
    """Prefer centred, symmetric, sharp frontal participant views."""
    gray = np.array(img.convert("L").resize((192, 144)), dtype=np.float32)
    h, w = gray.shape
    sharp = float(ImageStat.Stat(img.convert("L").resize((192, 144))).stddev[0]) / 64.0

    left = gray[:, : w // 2]
    right = gray[:, w // 2 :][:, ::-1]
    mse = float(np.mean((left - right) ** 2))
    symmetry = 1.0 / (1.0 + mse / 500.0)

    cy0, cy1 = h // 6, 2 * h // 3
    cx0, cx1 = w // 4, 3 * w // 4
    center_std = float(gray[cy0:cy1, cx0:cx1].std()) / 64.0

    left_edges = float(np.abs(np.diff(gray[:, : w // 2], axis=1)).mean())
    right_edges = float(np.abs(np.diff(gray[:, w // 2 :], axis=1)).mean())
    balance = 1.0 - min(abs(left_edges - right_edges) / (left_edges + right_edges + 1.0), 1.0)

    mass = gray - gray.mean()
    mass = np.clip(mass, 0, None)
    total = mass.sum() + 1e-6
    ys, xs = np.indices(gray.shape)
    cx = float((mass * xs).sum() / total) / w
    cy = float((mass * ys).sum() / total) / h
    center_penalty = abs(cx - 0.5) + 0.35 * abs(cy - 0.42)
    center_bonus = max(0.0, 0.55 - center_penalty)

    side_band = max(float(gray[:, : w // 8].mean()), float(gray[:, -w // 8 :].mean()))
    center_mean = float(gray[:, 3 * w // 8 : 5 * w // 8].mean())
    side_penalty = max(0.0, (side_band - center_mean) / 64.0)

    return (
        sharp * 0.22
        + symmetry * 0.24
        + center_std * 0.18
        + balance * 0.14
        + center_bonus * 0.14
        - side_penalty * 0.18
    )


def load_turns() -> list[dict]:
    return [json.loads(line) for line in (ROOT / "data" / "turns_user.jsonl").open()]


def ffmpeg_frame(video: Path, sec: float, out_jpg: Path) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{sec:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_jpg),
    ]
    subprocess.run(cmd, check=True)


def read_video_frame(video: Path, sec: float, tag: str) -> Image.Image:
    out_jpg = TMP / f"{tag}_{sec:.2f}.jpg"
    ffmpeg_frame(video, sec, out_jpg)
    return Image.open(out_jpg).convert("RGB")


def grab_turn_frame(turn: dict) -> Image.Image:
    vid = ROOT / "media" / turn["session_id"] / "whole_video.mp4"
    if not vid.exists():
        raise FileNotFoundError(vid)
    t0 = float(turn["t_start_sec"])
    t1 = float(turn["t_end_sec"]) if turn.get("t_end_sec") else t0 + 1.0
    tag = f"{turn['session_id']}_{turn.get('message_index', 0)}"
    return read_video_frame(vid, (t0 + t1) / 2.0, tag)


def crop_resize(img: Image.Image, thumb_w: int, thumb_h: int) -> Image.Image:
    w, h = img.size
    target = thumb_w / thumb_h
    cur = w / h
    if cur > target:
        nh = h
        nw = int(h * target)
        left = (w - nw) // 2
        img = img.crop((left, 0, left + nw, nh))
    else:
        nw = w
        nh = int(w / target)
        top = (h - nh) // 2
        img = img.crop((0, top, nw, top + nh))
    return img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)


def pick_frontal_turn(
    turns: list[dict],
    cls: str,
    filt,
    used_sessions: set[str],
    exclude_sessions: set[str] | None = None,
    extract: bool = True,
) -> tuple[dict, Image.Image | None, float]:
    exclude = set(used_sessions)
    if exclude_sessions:
        exclude |= exclude_sessions
    cands = [
        r
        for r in turns
        if r.get("cross_modal_turn_class") == cls
        and r["session_id"] not in exclude
        and filt(r)
        and len(r.get("content", "")) >= 8
        and "t_start_sec" in r
    ]
    by_session: dict[str, list[dict]] = {}
    for row in cands:
        by_session.setdefault(row["session_id"], []).append(row)
    for sid in by_session:
        by_session[sid].sort(key=lambda r: len(r.get("content", "")))

    if not extract:
        sid = sorted(by_session)[0]
        turn = by_session[sid][0]
        return turn, None, -1.0

    best_turn: dict | None = None
    best_img: Image.Image | None = None
    best_score = -1.0
    for sid in sorted(by_session):
        for turn in by_session[sid][:8]:
            try:
                img = grab_turn_frame(turn)
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
            score = frontal_score(img)
            if score > best_score:
                best_score = score
                best_turn = turn
                best_img = img
    if best_turn is None:
        raise RuntimeError(f"No frontal candidate for class {cls}")
    return best_turn, best_img, best_score


def find_turn(turns: list[dict], session_id: str, message_index: int) -> dict:
    for row in turns:
        if row["session_id"] == session_id and row.get("message_index") == message_index:
            return row
    raise RuntimeError(f"Turn not found: {session_id} #{message_index}")


def select_all_turns(turns: list[dict], extract: bool = True) -> list[tuple[str, list[dict]]]:
    used: set[str] = set()
    rows: list[tuple[str, list[dict]]] = []
    for quad_name, filters in QUADRANT_SPECS:
        exclude = {FIG4_CONFLICT_SESSION} if quad_name == "CONFLICT" else None
        quad_turns: list[dict] = []
        for i, filt in enumerate(filters):
            pin = PINNED_TURNS.get((quad_name, i))
            if pin is not None:
                turn = find_turn(turns, pin[0], pin[1])
                if turn["session_id"] in used:
                    raise RuntimeError(f"Pinned turn session already used: {pin[0]}")
                quad_turns.append(turn)
                used.add(turn["session_id"])
                print(
                    f"  pin {quad_name}[{i}]: {turn['session_id']} "
                    f"{turn['emotion_visual']}/{turn['sentiment']}"
                )
                continue
            turn, _img, score = pick_frontal_turn(
                turns, quad_name.lower(), filt, used, exclude, extract=extract
            )
            quad_turns.append(turn)
            used.add(turn["session_id"])
            print(
                f"  pick {quad_name}: {turn['session_id']} "
                f"{turn['emotion_visual']}/{turn['sentiment']} score={score:.3f}"
            )
        rows.append((quad_name, quad_turns))
    return rows


def compose_figure(
    quadrants: list[tuple[str, list[dict]]],
    images: dict[tuple[str, int], Image.Image],
) -> list[dict]:
    quad_w = 500
    thumb_w, thumb_h = 236, 178
    header_h = 30
    footer_h = 34
    inner_gap = 10
    quad_pad = 12
    grid_gap = 16
    outer_pad = 16
    fonts = (
        ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20),
        ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15),
    )
    font_title, font_body = fonts

    quad_inner_h = header_h + thumb_h + footer_h + quad_pad
    canvas_w = outer_pad + 2 * quad_w + grid_gap + outer_pad
    canvas_h = outer_pad + 2 * quad_inner_h + grid_gap + outer_pad
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    meta: list[dict] = []
    positions = [(0, 0), (1, 0), (0, 1), (1, 1)]
    for (qx, qy), (quad_name, quad_turns) in zip(positions, quadrants):
        x0 = outer_pad + qx * (quad_w + grid_gap)
        y0 = outer_pad + qy * (quad_inner_h + grid_gap)
        draw.text(
            (x0 + quad_w / 2, y0 + 4),
            quad_name,
            fill="#111111",
            font=font_title,
            anchor="ma",
        )
        block_w = 2 * thumb_w + inner_gap
        x_start = x0 + (quad_w - block_w) // 2
        img_y = y0 + header_h
        for i, turn in enumerate(quad_turns):
            x = x_start + i * (thumb_w + inner_gap)
            panel = crop_resize(images[(quad_name, i)], thumb_w, thumb_h)
            slug = f"{quad_name.lower()}_{i}"
            panel_path = OUT / f"_sample_{slug}.jpg"
            panel.save(panel_path, quality=92)
            canvas.paste(panel, (x, img_y))
            draw.text(
                (x + thumb_w / 2, img_y + thumb_h + 8),
                f"FER: {turn['emotion_visual']} | VADER: {turn['sentiment']}",
                fill="#222222",
                font=font_body,
                anchor="ma",
            )
            meta.append(
                {
                    "quadrant": quad_name,
                    "index": i,
                    "image": panel_path.name,
                    "session_id": turn["session_id"],
                    "message_index": turn["message_index"],
                    "emotion_visual": turn["emotion_visual"],
                    "sentiment": turn["sentiment"],
                    "content": turn["content"],
                }
            )

    canvas.save(OUT / "fig_dataset_samples.png", dpi=(300, 300))
    canvas.save(OUT / "fig_dataset_samples.pdf", "PDF", resolution=300.0)
    (OUT / "fig_dataset_samples_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose-only",
        action="store_true",
        help="Compose from existing _sample_{class}_{i}.jpg files",
    )
    args = parser.parse_args()

    turns = load_turns()
    quadrants = select_all_turns(turns, extract=not args.compose_only)

    images: dict[tuple[str, int], Image.Image] = {}
    if args.compose_only:
        for quad_name, quad_turns in quadrants:
            for i, _ in enumerate(quad_turns):
                slug = f"{quad_name.lower()}_{i}"
                images[(quad_name, i)] = Image.open(OUT / f"_sample_{slug}.jpg").convert("RGB")
    else:
        for quad_name, quad_turns in quadrants:
            for i, turn in enumerate(quad_turns):
                images[(quad_name, i)] = grab_turn_frame(turn)

    meta = compose_figure(quadrants, images)
    print("Wrote", OUT / "fig_dataset_samples.pdf")
    for row in meta:
        print(row)


if __name__ == "__main__":
    main()
