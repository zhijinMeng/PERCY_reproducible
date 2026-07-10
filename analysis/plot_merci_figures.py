#!/usr/bin/env python3
"""Generate MERCI journal figures from analysis/*.csv outputs."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ANALYSIS = ROOT / "analysis"
OUT = ROOT / "Figures"
OUT.mkdir(parents=True, exist_ok=True)

# Springer-friendly, print-safe palette
C_PRIMARY = "#1a5276"
C_ACCENT = "#c0392b"
C_CONFLICT_EDGE = "#922b21"  # darker red for conflict cell borders (print-visible)
C_NEUTRAL = "#7f8c8d"
C_STACK = ["#2e86c1", "#95a5a6", "#c0392b", "#8e44ad"]  # consistent, neutral, conflict, other
C_PANEL = "#d6eaf8"  # light blue panels (matches Blues heatmap family)
C_PANEL_ALT = "#ebf5fb"

# Illustrative conflict turn (cross_modal_conflict_turns.csv, message_index 12).
CONFLICT_EXAMPLE_SESSION = "00_00_00_02_07_00_00"
CONFLICT_EXAMPLE_T_MID_SEC = 531.765

EMOTIONS = ["happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"]
SENTIMENTS = ["positive", "neutral", "negative"]
# Pipeline text-7 labels (VADER expanded); column order matches cross_modal_7x7_text7_vader7.csv
TEXT7_COLS = ["happy", "neutral", "sad", "fear", "angry", "disgust", "surprise"]

VISUAL_POSITIVE = {"happy"}
VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}

# Fig. 3 (7x3) typography
MATRIX_AXIS_LABEL_FS = 15
MATRIX_TICK_FS = 15
MATRIX_CBAR_LABEL_FS = 13
MATRIX_CBAR_TICK_FS = 12
MATRIX_CELL_FS = 13
MATRIX_TITLE_FS = 15
# Fig. 4 (per-session): axis labels readable at \\linewidth scale in main.tex
SESSION_AXIS_LABEL_FS = 18
SESSION_TICK_FS = 15
SESSION_BAR_LABEL_FS = 15  # k/n above bars (vertical; dense x-axis)
SESSION_TITLE_FS = SESSION_AXIS_LABEL_FS
SESSION_MEDIAN_COLOR = C_CONFLICT_EDGE


def _parse_turn_class_counts() -> tuple[list[int], int]:
    """Read turn-class counts from cross_modal_summary.txt."""
    import re

    summary_path = ANALYSIS / "cross_modal_summary.txt"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing {summary_path}; run cross_modal_consistency.py first.")
    text = summary_path.read_text(encoding="utf-8")
    block = text.split("Turn-class counts", 1)[-1].split("7x3 visual", 1)[0]
    keys = ["consistent", "neutral", "conflict", "other"]
    counts = [0, 0, 0, 0]
    for line in block.splitlines():
        for idx, key in enumerate(keys):
            if not line.strip().lower().startswith(key):
                continue
            m = re.search(r":\s*(\d+)", line)
            if m:
                counts[idx] = int(m.group(1))
            break
    total = sum(counts)
    if total <= 0:
        raise ValueError(f"Could not parse turn-class counts from {summary_path}")
    return counts, total

# Fig. 4 (7x7): larger axis labels for print scaling
MATRIX_7X7_AXIS_LABEL_FS = 18
MATRIX_7X7_TICK_FS = 16
MATRIX_7X7_CELL_FS = 12
MATRIX_7X7_TITLE_FS = 16


def is_label_conflict_cell(visual: str, text7: str) -> bool:
    """Label-level mismatch stratum: both non-neutral, different labels."""
    if visual == "neutral" or text7 == "neutral":
        return False
    return visual != text7


def is_valence_conflict_cell(visual: str, sentiment: str) -> bool:
    """Valence-mismatch stratum (Section cross-modal-defs): not neutral on either axis."""
    if visual == "neutral" or sentiment == "neutral":
        return False
    if visual in VISUAL_POSITIVE and sentiment == "negative":
        return True
    if visual in VISUAL_NEGATIVE and sentiment == "positive":
        return True
    return False


def fig_cross_modal_confusion_matrix() -> None:
    """7x3 valence heatmap with explicit cell fills (PDF-safe colours and labels)."""
    from matplotlib.colors import PowerNorm
    from matplotlib.patches import Rectangle
    from matplotlib.cm import ScalarMappable

    path = ANALYSIS / "cross_modal_confusion.csv"
    if not path.exists():
        raise FileNotFoundError(f"Run cross_modal_consistency.py first; missing {path}")

    df = pd.read_csv(path)
    df["emotion"] = df["emotion"].str.strip().str.lower()
    counts = np.zeros((len(EMOTIONS), len(SENTIMENTS)), dtype=int)
    for i, em in enumerate(EMOTIONS):
        row = df.loc[df["emotion"] == em]
        if row.empty:
            continue
        for j, sn in enumerate(SENTIMENTS):
            counts[i, j] = int(row[f"{sn}_n"].iloc[0])

    n_turns = int(counts.sum())
    row_sums = counts.sum(axis=1, keepdims=True)
    row_pct = np.zeros_like(counts, dtype=float)
    np.divide(counts, row_sums, out=row_pct, where=row_sums > 0)
    row_pct *= 100

    # Colour = row-normalised % (0--100); PowerNorm keeps low-% cells visible in print.
    # Cap the Blues ramp so 100% cells stay light enough for black text.
    from matplotlib.colors import LinearSegmentedColormap

    base = plt.colormaps["Blues"]
    cmap = LinearSegmentedColormap.from_list(
        "BluesLight",
        [base(x) for x in np.linspace(0.05, 0.72, 256)],
    )
    norm = PowerNorm(gamma=0.55, vmin=0, vmax=100)
    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])

    n_rows, n_cols = len(EMOTIONS), len(SENTIMENTS)
    # Wide cells: full-width single-column figure (avoid squashed x labels).
    cell_w, cell_h = 2.35, 0.88
    plot_w = n_cols * cell_w
    plot_h = n_rows * cell_h

    fig, ax = plt.subplots(figsize=(9.2, 6.6))
    ax.set_xlim(0, plot_w)
    ax.set_ylim(plot_h, 0)
    ax.set_aspect("auto")

    conflict_boxes: list[tuple[float, float]] = []

    # Pass 1: cell fills (no edge — avoids neighbours clipping thick borders).
    for i, vis in enumerate(EMOTIONS):
        for j, sn in enumerate(SENTIMENTS):
            n = int(counts[i, j])
            pct = float(row_pct[i, j])
            conflict = is_valence_conflict_cell(vis, sn)
            x0 = j * cell_w
            y0 = i * cell_h
            xc = x0 + cell_w / 2
            yc = y0 + cell_h / 2

            if n == 0:
                face = "#e8ecf0"
                label = "0\n(0%)"
            else:
                face = cmap(norm(pct))
                label = f"{n}\n({pct:.0f}%)"

            ax.add_patch(
                Rectangle(
                    (x0, y0),
                    cell_w,
                    cell_h,
                    facecolor=face,
                    edgecolor="none",
                    linewidth=0,
                    zorder=1,
                )
            )
            if conflict and n > 0:
                conflict_boxes.append((x0, y0))
            ax.text(
                xc,
                yc,
                label,
                ha="center",
                va="center",
                fontsize=MATRIX_CELL_FS,
                color="#111111",
                fontweight="bold" if conflict and n > 0 else "semibold",
                zorder=4,
            )

    # Pass 2: uniform thin grid on every cell.
    for i in range(n_rows):
        for j in range(n_cols):
            ax.add_patch(
                Rectangle(
                    (j * cell_w, i * cell_h),
                    cell_w,
                    cell_h,
                    fill=False,
                    edgecolor="#5d6d7e",
                    linewidth=1.0,
                    zorder=2,
                )
            )

    # Pass 3: full red box on top (all four sides visible).
    for x0, y0 in conflict_boxes:
        ax.add_patch(
            Rectangle(
                (x0, y0),
                cell_w,
                cell_h,
                fill=False,
                edgecolor=C_CONFLICT_EDGE,
                linewidth=5.0,
                joinstyle="miter",
                zorder=3,
            )
        )

    ax.set_xticks([(j + 0.5) * cell_w for j in range(n_cols)])
    ax.set_xticklabels(["Positive", "Neutral", "Negative"], fontsize=MATRIX_TICK_FS)
    ax.set_yticks([(i + 0.5) * cell_h for i in range(n_rows)])
    ax.set_yticklabels([e.capitalize() for e in EMOTIONS], fontsize=MATRIX_TICK_FS)
    ax.set_xlabel("Text sentiment (VADER)", fontsize=MATRIX_AXIS_LABEL_FS, labelpad=8)
    ax.set_ylabel("Visual emotion (FER)", fontsize=MATRIX_AXIS_LABEL_FS, labelpad=8)
    ax.set_title(
        f"Cross-modal $7\\times3$ valence heatmap ($n={n_turns}$)",
        fontsize=MATRIX_TITLE_FS,
        pad=10,
    )
    ax.tick_params(top=False, right=False, axis="x", pad=4)

    fig.subplots_adjust(left=0.11, right=0.86, top=0.92, bottom=0.10)
    cbar = fig.colorbar(sm, ax=ax, location="right", fraction=0.04, pad=0.02, shrink=0.92)
    cbar.set_label("Row %", fontsize=MATRIX_CBAR_LABEL_FS)
    cbar.set_ticks([0, 25, 50, 75, 100])
    cbar.ax.tick_params(labelsize=MATRIX_CBAR_TICK_FS)
    _save(fig, "fig_cross_modal_confusion")


def _plot_cross_modal_7x7_from_csv(
    csv_path: Path,
    stem: str,
    title: str,
    xlabel: str,
) -> None:
    """Shared 7x7 matrix renderer (pipeline VADER-7, offline HF, lexicon, ...)."""
    # Cap the Blues ramp so 100% cells stay light enough for black text.
    from matplotlib.colors import LinearSegmentedColormap, PowerNorm
    from matplotlib.patches import Rectangle
    from matplotlib.cm import ScalarMappable

    if not csv_path.exists():
        raise FileNotFoundError(f"Missing {csv_path}; run cross_modal_7x7.py first.")

    df = pd.read_csv(csv_path, index_col=0)
    df.index = [str(x).strip().lower() for x in df.index]
    df = df.reindex(EMOTIONS)
    counts = df[TEXT7_COLS].fillna(0).values.astype(int)
    n_rows, n_cols = len(EMOTIONS), len(TEXT7_COLS)
    row_sums = counts.sum(axis=1, keepdims=True)
    row_pct = np.zeros_like(counts, dtype=float)
    np.divide(counts, row_sums, out=row_pct, where=row_sums > 0)
    row_pct *= 100
    n_turns = int(counts.sum())

    base = plt.colormaps["Blues"]
    cmap = LinearSegmentedColormap.from_list(
        "BluesLight",
        [base(x) for x in np.linspace(0.05, 0.72, 256)],
    )
    norm = PowerNorm(gamma=0.55, vmin=0, vmax=100)
    sm = ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])

    cell_w, cell_h = 1.48, 0.92
    plot_w = n_cols * cell_w
    plot_h = n_rows * cell_h

    fig, ax = plt.subplots(figsize=(11.8, 7.0))
    ax.set_xlim(0, plot_w)
    ax.set_ylim(plot_h, 0)
    ax.set_aspect("auto")

    conflict_boxes: list[tuple[float, float]] = []

    for i, vis in enumerate(EMOTIONS):
        for j, txt7 in enumerate(TEXT7_COLS):
            n = int(counts[i, j])
            pct = float(row_pct[i, j])
            conflict = is_label_conflict_cell(vis, txt7)
            x0 = j * cell_w
            y0 = i * cell_h
            xc = x0 + cell_w / 2
            yc = y0 + cell_h / 2

            if n == 0:
                face = "#e8ecf0"
                label = "0"
            else:
                face = cmap(norm(pct))
                label = f"{n}\n({pct:.0f}%)"

            ax.add_patch(
                Rectangle(
                    (x0, y0), cell_w, cell_h,
                    facecolor=face, edgecolor="none", linewidth=0, zorder=1,
                )
            )
            if conflict and n > 0:
                conflict_boxes.append((x0, y0))
            ax.text(
                xc, yc, label,
                ha="center", va="center", fontsize=MATRIX_7X7_CELL_FS,
                color="#111111" if n else "#90a4ae",
                fontweight="bold" if conflict and n > 0 else "normal",
                zorder=4,
            )

    for i in range(n_rows):
        for j in range(n_cols):
            ax.add_patch(
                Rectangle(
                    (j * cell_w, i * cell_h), cell_w, cell_h,
                    fill=False, edgecolor="#5d6d7e", linewidth=1.0, zorder=2,
                )
            )

    for x0, y0 in conflict_boxes:
        ax.add_patch(
            Rectangle(
                (x0, y0), cell_w, cell_h,
                fill=False, edgecolor=C_CONFLICT_EDGE, linewidth=5.0,
                joinstyle="miter", zorder=3,
            )
        )

    ax.set_xticks([(j + 0.5) * cell_w for j in range(n_cols)])
    ax.set_xticklabels(
        [e.capitalize() for e in TEXT7_COLS],
        fontsize=MATRIX_7X7_TICK_FS,
        rotation=32,
        ha="right",
    )
    ax.set_yticks([(i + 0.5) * cell_h for i in range(n_rows)])
    ax.set_yticklabels([e.capitalize() for e in EMOTIONS], fontsize=MATRIX_7X7_TICK_FS)
    ax.set_xlabel(xlabel, fontsize=MATRIX_7X7_AXIS_LABEL_FS, labelpad=12)
    ax.set_ylabel("Visual emotion (FER)", fontsize=MATRIX_7X7_AXIS_LABEL_FS, labelpad=8)
    ax.set_title(title, fontsize=MATRIX_7X7_TITLE_FS, pad=10)
    ax.tick_params(top=False, right=False, axis="both", labelsize=MATRIX_7X7_TICK_FS)

    fig.subplots_adjust(left=0.09, right=0.88, top=0.92, bottom=0.18)
    cbar = fig.colorbar(sm, ax=ax, location="right", fraction=0.035, pad=0.02, shrink=0.9)
    cbar.set_label("Row %", fontsize=MATRIX_CBAR_LABEL_FS)
    cbar.set_ticks([0, 25, 50, 75, 100])
    cbar.ax.tick_params(labelsize=MATRIX_CBAR_TICK_FS)
    _save(fig, stem)


def fig_cross_modal_7x7_matrix() -> None:
    """7x7 matrix: visual FER vs pipeline sentiment_emotion_7 (VADER expansion)."""
    _plot_cross_modal_7x7_from_csv(
        ANALYSIS / "cross_modal_7x7_text7_vader7.csv",
        "fig_cross_modal_7x7",
        title="Cross-modal $7\\times7$ matrix (pipeline VADER$\\rightarrow$7)",
        xlabel="Text emotion (pipeline sentiment_emotion_7)",
    )


def fig_cross_modal_7x7_hf() -> None:
    """7x7 matrix: visual FER vs offline DistilRoBERTa text-emotion labels."""
    _plot_cross_modal_7x7_from_csv(
        ANALYSIS / "cross_modal_7x7_text7_hf.csv",
        "fig_cross_modal_7x7_hf",
        title="Cross-modal $7\\times7$ heatmap (offline DistilRoBERTa)",
        xlabel="Text emotion (DistilRoBERTa)",
    )


def fig_cross_modal_7x7_lexicon() -> None:
    """7x7 matrix: visual FER vs lexicon baseline text-emotion labels."""
    _plot_cross_modal_7x7_from_csv(
        ANALYSIS / "cross_modal_7x7_text7_lexicon.csv",
        "fig_cross_modal_7x7_lexicon",
        title="Cross-modal $7\\times7$ matrix (lexicon baseline)",
        xlabel="Text emotion (offline lexicon baseline)",
    )


def fig_turn_class_composition() -> None:
    """Four-class breakdown: one horizontal bar per class (readable labels for all strata)."""
    counts, total = _parse_turn_class_counts()
    labels = ["Consistent", "Neutral", "Conflict", "Other"]
    pcts = [c / total * 100 for c in counts]

    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    y = np.arange(len(labels))
    bars = ax.barh(
        y,
        pcts,
        color=C_STACK,
        height=0.58,
        edgecolor="white",
        linewidth=1.2,
    )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlim(0, 78)
    ax.set_xlabel("Share of analysed user turns (%)")
    ax.set_title(f"Turn-level cross-modal classes (n={total})")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    for rect, c, p, col in zip(bars, counts, pcts, C_STACK):
        ax.text(
            min(p + 1.5, 76),
            rect.get_y() + rect.get_height() / 2,
            f"{c} ({p:.1f}%)",
            va="center",
            ha="left",
            fontsize=9,
            fontweight="bold",
            color=col,
        )
        if p >= 6:
            ax.text(
                p / 2,
                rect.get_y() + rect.get_height() / 2,
                f"{p:.1f}%",
                va="center",
                ha="center",
                fontsize=9,
                fontweight="bold",
                color="white",
            )

    fig.tight_layout()
    _save(fig, "fig_turn_class_composition")


def fig_per_session_conflict() -> None:
    path = ANALYSIS / "cross_modal_per_session.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run cross_modal_consistency.py first.")

    df = pd.read_csv(path)
    if "conflict_rate_pct" not in df.columns and "conflict_rate" in df.columns:
        df["conflict_rate_pct"] = df["conflict_rate"]
    if "conflict_n" not in df.columns:
        if "conflict" in df.columns:
            df["conflict_n"] = df["conflict"]
        else:
            df["conflict_n"] = df.get("conflicts", df.get("n_conflict", 0))
    if "n_turns" not in df.columns:
        df["n_turns"] = df.get("n_user_turns", df.get("turns", 0))
    if "session_id" not in df.columns:
        df["session_id"] = [f"S{i+1:02d}" for i in range(len(df))]

    # Sessions with conflict first (high→low), then 0% sessions grouped on the right
    # so empty rows are not buried at the bottom of a horizontal chart.
    df["_has_conflict"] = df["conflict_n"].astype(int) > 0
    df = df.sort_values(
        ["_has_conflict", "conflict_rate_pct"],
        ascending=[False, False],
    ).reset_index(drop=True)
    df["label"] = [f"S{i + 1:02d}" for i in range(len(df))]

    med = float(df["conflict_rate_pct"].median())
    total_conflicts = int(df["conflict_n"].sum())
    total_turns = int(df["n_turns"].sum())
    n_zero = int((df["conflict_n"] == 0).sum())
    n_nonzero = len(df) - n_zero

    fig, ax = plt.subplots(figsize=(11.5, 6.8))
    x = np.arange(len(df))
    rates = df["conflict_rate_pct"].astype(float).values
    colors = []
    for _, row in df.iterrows():
        if int(row["conflict_n"]) == 0:
            colors.append("#bdc3c7")
        elif float(row["conflict_rate_pct"]) >= med:
            colors.append(C_ACCENT)
        else:
            colors.append(C_PRIMARY)

    ax.bar(x, rates, width=0.78, color=colors, edgecolor="#5d6d7e", linewidth=0.35)
    ax.axhline(
        med,
        color=SESSION_MEDIAN_COLOR,
        linestyle="--",
        linewidth=1.4,
        label=f"Median = {med:.1f}%",
    )

    rate_max = float(rates.max())
    # Headroom for vertical k/n labels on the tallest bar (S01 ≈ 54.5%).
    y_top = rate_max + 12.0

    # Visual break between conflict-bearing and all-zero sessions.
    if n_zero > 0 and n_nonzero > 0:
        split_x = n_nonzero - 0.5
        ax.axvline(split_x, color="#7f8c8d", linestyle=":", linewidth=1.0, alpha=0.85)
        ymax = y_top
        ax.text(
            (n_nonzero - 1) / 2.0,
            ymax * 0.94,
            f"{n_nonzero} sessions with $\\geq$1 conflict",
            ha="center",
            va="top",
            fontsize=SESSION_TICK_FS,
            color="#1a5276",
        )
        ax.text(
            n_nonzero + (n_zero - 1) / 2.0,
            ymax * 0.94,
            f"{n_zero} sessions at 0%",
            ha="center",
            va="top",
            fontsize=SESSION_TICK_FS,
            color="#7f8c8d",
        )

    for xi, row in zip(x, df.itertuples(index=False)):
        k, n = int(row.conflict_n), int(row.n_turns)
        if k > 0:
            y_bar = float(row.conflict_rate_pct)
            ax.text(
                xi,
                y_bar + max(1.0, y_bar * 0.02),
                f"{k}/{n}",
                ha="center",
                va="bottom",
                fontsize=SESSION_BAR_LABEL_FS,
                color="#1a5276",
                rotation=90,
                clip_on=False,
            )

    ax.set_xticks(x, df["label"].tolist(), fontsize=SESSION_TICK_FS - 1, rotation=90)
    ax.set_ylabel("Valence conflict rate (%)", fontsize=SESSION_AXIS_LABEL_FS)
    ax.set_xlabel(
        "Session (sorted: conflict rate high to low, then 0%)",
        fontsize=SESSION_AXIS_LABEL_FS,
    )
    ax.set_title(
        f"Per-session valence conflict ({len(df)} sessions; "
        f"{total_conflicts}/{total_turns} conflict turns)",
        fontsize=SESSION_TITLE_FS,
    )
    ax.set_ylim(0, y_top)
    ax.set_xlim(-0.6, len(df) - 0.4)
    ax.tick_params(axis="y", labelsize=SESSION_TICK_FS)
    ax.legend(loc="upper right", fontsize=SESSION_TICK_FS, frameon=False)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.24)
    for ext in ("pdf", "png"):
        path = OUT / f"fig_per_session_conflict.{ext}"
        fig.savefig(
            path,
            dpi=300 if ext == "png" else None,
            bbox_inches="tight",
            pad_inches=0.18,
            facecolor="white",
        )
        print(f"Wrote {path}")
    plt.close(fig)


def _research_root() -> Path:
    p = ROOT.resolve()
    for _ in range(8):
        if (p / "HF_Data").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return ROOT.parent.parent.parent


def _conflict_example_video() -> Path | None:
    sid = CONFLICT_EXAMPLE_SESSION
    for base in (
        _research_root() / "HF_Data/percy_data/normalized_media",
        _research_root() / "MERCI_Plus/data",
        ROOT.parent / "HF_Data/percy_data/normalized_media",
    ):
        vp = base / sid / "whole_video.mp4"
        if vp.is_file():
            return vp
    return None


def _ensure_conflict_example_face(out_path: Path) -> Path:
    """Crop participant frame at the audited conflict turn (ffmpeg + PIL)."""
    if out_path.is_file():
        return out_path

    import subprocess

    from PIL import Image

    video = _conflict_example_video()
    if video is None:
        raise FileNotFoundError(
            f"Missing whole_video.mp4 for session {CONFLICT_EXAMPLE_SESSION}; "
            "link normalized_media under HF_Data/ or MERCI_Plus/data/."
        )

    raw = out_path.with_name("_conflict_example_frame_raw.jpg")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            str(CONFLICT_EXAMPLE_T_MID_SEC),
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-update",
            "1",
            "-q:v",
            "2",
            str(raw),
        ],
        check=True,
        capture_output=True,
    )
    im = Image.open(raw)
    w, h = im.size
    crop = im.crop((int(w * 0.28), int(h * 0.05), int(w * 0.72), int(h * 0.88)))
    crop.resize((480, 534), Image.Resampling.LANCZOS).save(out_path, quality=92)
    return out_path


def _styled_panel(ax, *, facecolor: str, edgecolor: str = C_PRIMARY, lw: float = 1.5) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_axis_off()
    ax.set_facecolor(facecolor)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor(edgecolor)
        spine.set_linewidth(lw)


def _conflict_example_columns(
    fig: plt.Figure, m: float, gap: float, *, hdr_band: float
) -> tuple[plt.Axes, plt.Axes, plt.Axes, plt.Axes]:
    """Four equal-width panels; hdr_band reserves space for figure-level titles."""
    inner_w = 1.0 - 2 * m
    col_w = (inner_w - 3 * gap) / 4.0
    h = 1.0 - 2 * m - hdr_band
    xs = [m + i * (col_w + gap) for i in range(4)]
    return tuple(fig.add_axes([x, m, col_w, h]) for x in xs)


def _load_conflict_example_turn() -> dict:
    """Audited turn message_index=12 (session 00_00_00_02_07_00_00)."""
    import json

    sid = CONFLICT_EXAMPLE_SESSION
    for base in (
        _research_root() / "HF_Data/percy_data/normalized_media",
        _research_root() / "MERCI_Plus/data",
        ROOT.parent / "HF_Data/percy_data/normalized_media",
    ):
        path = base / sid / "chat_history.json"
        if not path.is_file():
            continue
        for msg in json.loads(path.read_text(encoding="utf-8")):
            if msg.get("role") != "user":
                continue
            if int(msg.get("message_index", -1)) == 12:
                return msg
    return {
        "content": (
            "I'm now very stressful and trying to make the decision "
            "whether I should study a Ph.D. or not."
        ),
        "emotion_visual": "happy",
        "sentiment": "negative",
        "sentiment_score": -0.5563,
        "fer_probs": {"happy": 0.8609, "neutral": 0.1349},
    }


def _conflict_example_headers(
    fig: plt.Figure,
    axes: tuple[plt.Axes, ...],
    titles: tuple[str, ...],
    *,
    fs: float,
    margin: float,
) -> None:
    """Titles just below the top red border (figure coordinates, one baseline)."""
    y = 1.0 - margin - 0.050
    for ax, title in zip(axes, titles):
        pos = ax.get_position()
        fig.text(
            pos.x0 + pos.width / 2,
            y,
            title,
            ha="center",
            va="top",
            fontsize=fs,
            fontweight="bold",
            color=C_PRIMARY,
        )


def fig_conflict_example_turn() -> None:
    """Four-column banner: FER | face frame | transcript | VADER."""
    import textwrap

    from matplotlib.image import imread
    from matplotlib.patches import Rectangle

    turn = _load_conflict_example_turn()
    utterance = str(turn.get("content", "")).strip()
    face_label = str(turn.get("emotion_visual", "happy")).lower()
    text_polarity = str(turn.get("sentiment", "negative")).lower()
    vader_compound = float(turn.get("sentiment_score", -0.5563))
    fer_probs = turn.get("fer_probs") or {}
    fer_p = float(fer_probs.get(face_label, 0.0))

    face_path = _ensure_conflict_example_face(OUT / "conflict_example_face.jpg")
    face_img = imread(face_path)

    m, gap = 0.022, 0.012
    hdr_band = 0.088
    hdr_fs = SESSION_AXIS_LABEL_FS  # match Fig. 4 axis label size
    label_fs = 26
    param_fs = 12.5
    quote_fs = 16.0

    fig = plt.figure(figsize=(11.0, 3.05), facecolor="white")
    outer = fig.add_axes([0, 0, 1, 1])
    outer.set_axis_off()
    outer.add_patch(
        Rectangle(
            (m, m),
            1 - 2 * m,
            1 - 2 * m,
            fill=True,
            facecolor="#f8fbfd",
            edgecolor=C_CONFLICT_EDGE,
            linewidth=2.4,
            transform=outer.transAxes,
            zorder=0,
            clip_on=False,
        )
    )

    axes = _conflict_example_columns(fig, m, gap, hdr_band=hdr_band)
    ax_fer, ax_img, ax_asr, ax_vad = axes
    _conflict_example_headers(
        fig,
        axes,
        ("FER", "Video frame", "Transcript (ASR)", "VADER"),
        fs=hdr_fs,
        margin=m,
    )

    quote = textwrap.fill(f'"{utterance}"', width=20)

    # Col 1 — FER result
    _styled_panel(ax_fer, facecolor=C_PANEL)
    ax_fer.text(
        0.5,
        0.60,
        face_label.capitalize(),
        ha="center",
        va="center",
        fontsize=label_fs,
        fontweight="bold",
        color=C_STACK[0],
    )
    ax_fer.text(
        0.5,
        0.40,
        f"p({face_label}) = {fer_p:.2f}",
        ha="center",
        va="center",
        fontsize=param_fs,
        color=C_PRIMARY,
    )
    ax_fer.text(
        0.5,
        0.22,
        "Face valence:\npositive",
        ha="center",
        va="center",
        fontsize=param_fs,
        color=C_PRIMARY,
        linespacing=1.25,
    )

    # Col 2 — video frame (bottom-anchored, small margin above panel floor)
    _styled_panel(ax_img, facecolor="white", edgecolor=C_PRIMARY)
    ar = face_img.shape[1] / max(face_img.shape[0], 1)
    y_lo, y_hi = 0.07, 0.84
    x_pad = 0.04
    avail_h = y_hi - y_lo
    avail_w = 1.0 - 2 * x_pad
    box_h = avail_h
    box_w = box_h * ar
    if box_w > avail_w:
        box_w = avail_w
        box_h = box_w / ar
    xc = 0.5
    x0, x1 = xc - box_w / 2, xc + box_w / 2
    y0, y1 = y_lo, y_lo + box_h
    ax_img.imshow(face_img, extent=[x0, x1, y0, y1], aspect="equal", zorder=2)

    # Col 3 — ASR transcript
    _styled_panel(ax_asr, facecolor=C_PANEL_ALT)
    ax_asr.text(
        0.5,
        0.48,
        quote,
        ha="center",
        va="center",
        fontsize=quote_fs,
        fontweight="medium",
        color="#111111",
        linespacing=1.4,
    )

    # Col 4 — VADER result
    _styled_panel(ax_vad, facecolor=C_PANEL_ALT)
    ax_vad.text(
        0.5,
        0.58,
        text_polarity.capitalize(),
        ha="center",
        va="center",
        fontsize=label_fs,
        fontweight="bold",
        color=C_ACCENT,
    )
    ax_vad.text(
        0.5,
        0.36,
        f"Compound:\n{vader_compound:+.4f}",
        ha="center",
        va="center",
        fontsize=param_fs,
        color=C_PRIMARY,
        linespacing=1.25,
    )
    ax_vad.text(
        0.5,
        0.16,
        "Text valence:\nnegative",
        ha="center",
        va="center",
        fontsize=param_fs,
        color=C_PRIMARY,
        linespacing=1.25,
    )

    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    _save(fig, "fig_conflict_example")


def fig_response_latency() -> None:
    df = pd.read_csv(ANALYSIS / "response_latency.csv")
    clean = df.loc[~df["filtered"].astype(bool), "latency_s"].astype(float)
    clean = clean[(clean >= 0) & (clean <= 60)]

    fig, ax = plt.subplots(figsize=(5.2, 3.6))
    bp = ax.boxplot(
        clean,
        vert=True,
        widths=0.45,
        patch_artist=True,
        showfliers=True,
        medianprops=dict(color=C_ACCENT, linewidth=2),
        boxprops=dict(facecolor="#d6eaf8", edgecolor=C_PRIMARY),
        whiskerprops=dict(color=C_PRIMARY),
        capprops=dict(color=C_PRIMARY),
    )
    _ = bp
    med = clean.median()
    ax.scatter([1], [med], s=48, zorder=5, color=C_ACCENT, label=f"Median = {med:.2f} s")
    ax.set_xticks([1], ["Clean pairs"])
    ax.set_ylabel("Inter-turn gap Δt (s)")
    ax.set_title(f"Deployment-context response gaps (n={len(clean)} clean pairs, 30 sessions)")
    ax.set_ylim(0, min(60, clean.quantile(0.99) * 1.15))
    ax.legend(loc="upper right", fontsize=9)
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    fig.tight_layout()
    _save(fig, "fig_response_latency")


def _save(fig: plt.Figure, stem: str) -> None:
    for ext in ("pdf", "png"):
        path = OUT / f"{stem}.{ext}"
        fig.savefig(
            path,
            dpi=300 if ext == "png" else None,
            bbox_inches="tight",
            pad_inches=0.12,
            facecolor="white",
        )
        print(f"Wrote {path}")
    plt.close(fig)


def main() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig_conflict_example_turn()
    fig_cross_modal_confusion_matrix()
    fig_cross_modal_7x7_hf()
    fig_turn_class_composition()
    fig_per_session_conflict()
    fig_response_latency()
    print("Done.")


if __name__ == "__main__":
    main()
