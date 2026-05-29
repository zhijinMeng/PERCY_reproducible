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
# Fig. 5 (per-session): match matrix typography
SESSION_AXIS_LABEL_FS = 11
SESSION_TICK_FS = 10
SESSION_TITLE_FS = 12
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
    """7x3 confusion matrix with explicit cell fills (PDF-safe colours and labels)."""
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
    cmap = plt.colormaps["Blues"]
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
        f"Cross-modal confusion matrix ($7\\times3$, $n={n_turns}$)",
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
    from matplotlib.colors import PowerNorm
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

    cmap = plt.colormaps["Blues"]
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
        title="Cross-modal $7\\times7$ matrix (offline DistilRoBERTa)",
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
    counts, total = _parse_turn_class_counts()
    labels = ["Consistent", "Neutral", "Conflict", "Other"]
    pcts = [c / total * 100 for c in counts]

    fig, ax = plt.subplots(figsize=(5.5, 2.8))
    left = 0
    for lab, c, p, col in zip(labels, counts, pcts, C_STACK):
        ax.barh(0, p, left=left, height=0.45, color=col, edgecolor="white", linewidth=1.2)
        if p >= 8:
            ax.text(
                left + p / 2, 0, f"{lab}\n{c} ({p:.1f}%)",
                ha="center", va="center", fontsize=9,
                color="white", fontweight="bold",
            )
        left += p
    ax.set_xlim(0, 100)
    ax.set_yticks([])
    ax.set_xlabel("Share of analysed user turns (%)")
    ax.set_title(f"Turn-level cross-modal classes (n={total})")
    ax.legend(
        [plt.Rectangle((0, 0), 1, 1, color=c) for c in C_STACK],
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        ncol=4,
        frameon=False,
        fontsize=9,
    )
    fig.tight_layout()
    _save(fig, "fig_turn_class_composition")


def fig_per_session_conflict() -> None:
    path = ANALYSIS / "cross_modal_per_session.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run cross_modal_consistency.py first.")

    df = pd.read_csv(path)
    # Expected columns: session_id, n_turns, conflict_n, conflict_rate_pct
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

    df = df.sort_values("conflict_rate_pct", ascending=True).reset_index(drop=True)
    med = float(df["conflict_rate_pct"].median())
    total_conflicts = int(df["conflict_n"].sum())
    total_turns = int(df["n_turns"].sum())

    # Match Fig. 3--4 typography; use conflict palette for high-rate sessions.
    fig, ax = plt.subplots(figsize=(9.2, 6.6))
    y = np.arange(len(df))
    colors = [C_ACCENT if r >= med else C_PRIMARY for r in df["conflict_rate_pct"]]
    ax.barh(y, df["conflict_rate_pct"], color=colors, height=0.72, edgecolor="none")
    ax.axvline(
        med,
        color=SESSION_MEDIAN_COLOR,
        linestyle="--",
        linewidth=1.4,
        label=f"Median = {med:.1f}%",
    )

    sid_map = {sid: f"S{i+1:02d}" for i, sid in enumerate(df["session_id"].tolist())}
    ylabels = []
    for _, row in df.iterrows():
        sid = sid_map[str(row["session_id"])]
        k, n = int(row["conflict_n"]), int(row["n_turns"])
        ylabels.append(f"{sid}  ({k}/{n})")
    ax.set_yticks(y, ylabels, fontsize=SESSION_TICK_FS)
    ax.set_xlabel("Conflict rate in session (%)", fontsize=SESSION_AXIS_LABEL_FS)
    ax.set_title(
        f"Per-session valence conflict ({len(df)} sessions; "
        f"{total_conflicts}/{total_turns} conflict turns)",
        fontsize=SESSION_TITLE_FS,
    )
    ax.set_xlim(0, max(55, float(df["conflict_rate_pct"].max()) * 1.08))
    ax.tick_params(axis="x", labelsize=SESSION_TICK_FS)

    ax.legend(loc="lower right", fontsize=SESSION_TICK_FS, frameon=False)
    fig.subplots_adjust(left=0.36, right=0.97, top=0.94, bottom=0.10)
    _save(fig, "fig_per_session_conflict")


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
    fig_cross_modal_confusion_matrix()
    fig_cross_modal_7x7_hf()
    fig_turn_class_composition()
    fig_per_session_conflict()
    fig_response_latency()
    print("Done.")


if __name__ == "__main__":
    main()
