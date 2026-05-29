"""
Personality alignment analysis for MERCI (extends Decision A).

Three psychometric scales from the post-survey are scored per participant
on the N=20 matched pairs:

  1. Self-TIPI        (QID108_1..10)  -- Big Five personality of the user
     Gosling et al. 2003 scoring (reverse items 2,4,6,8,10).
  2. Robot-TIPI       (QID99_1..10)   -- Big Five personality attributed
     to the robot by the same participant.  Items are in the same order
     as the self-TIPI, so the same scoring function applies.
  3. NARS-short       (QID89_1..4)    -- 4-item Negative Attitudes towards
     Robots Scale with Emotions sub-factor.  Item 1 is negatively keyed;
     the total is the summed score (reversed) on 1..5.

Analyses produced:

  A. Sample description of the three scales (mean, SD, range).
  B. User personality vs objective behaviour + vs subjective experience
     Likert subscales  (5 Big-Five x (7 UX + 6 TLX + 6 objective) = 95).
  C. Robot personality vs the same (95 more).
  D. Self-Robot personality alignment: do users who rate themselves high
     on trait X also rate the robot high on trait X?  (5 correlations).
  E. NARS pre-attitude vs subjective experience + objective behaviour
     (1 x 13 = 13 correlations).

For every correlation grid we compute Spearman rho, a t-approximation
two-sided p, and Benjamini-Hochberg FDR across that grid.

Outputs (all in Paper_writing/Claude_Writing/):
  personality_pair_data.csv        : per-pair long table
  personality_tipi_user.csv        : Big-Five scores per pair
  personality_tipi_robot.csv       : robot Big-Five per pair
  personality_nars.csv             : NARS per pair
  personality_alignment.csv        : all correlations (grid, rho, p, q)
  personality_summary.txt          : narrative summary
  personality_selfrobot_scatter.png: 5-panel self vs robot scatter
  personality_heatmap_user.png     : user-BF x (UX+TLX+obj) heatmap
  personality_heatmap_robot.png    : robot-BF x (UX+TLX+obj) heatmap
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

# reuse helpers from subj_obj_alignment
from subj_obj_alignment import (
    SURVEY_CSV,
    read_survey,
    likert_to_int,
    read_latency,
    find_chat,
    extract_chat_features,
    LIKERT_GROUPS,
    NASA_TLX_GROUPS,
    compute_subscale,
    spearman,
    spearman_p_two_sided,
    bh_fdr,
)

ROOT = Path(r"c:\Users\z5430888\OneDrive - UNSW\Research Project\OneDrive_2026-04-02")
OUT_DIR = ROOT / "Paper_writing" / "Claude_Writing" / "analysis"
MAPPING_CSV = OUT_DIR.parent / "mapping" / "FINAL_session_post_mapping.csv"


# ---- scale scoring ----
def score_tipi(row: dict, prefix: str) -> dict[str, float | None]:
    """prefix e.g. 'QID108_' (self) or 'QID99_' (robot).
    Returns a dict keyed Extraversion/Agreeableness/Conscientiousness/
    EmotionalStability/Openness with values on the 1..7 scale, or None
    if any required item is missing."""
    items = [likert_to_int(row.get(f"{prefix}{i}", "")) for i in range(1, 11)]
    # Require all 10 items; TIPI subscales are 2-item averages so a single
    # missing item already destroys one trait; requiring all 10 is cleaner.
    if any(v is None for v in items):
        return {k: None for k in (
            "Extraversion", "Agreeableness", "Conscientiousness",
            "EmotionalStability", "Openness")}
    i = items                                   # alias, 0-indexed
    # Reverse-score items 2,4,6,8,10 on 1..7 scale: r = 8 - v
    def rev(v): return 8 - v
    return {
        "Extraversion":         (i[0] + rev(i[5])) / 2,     # 1, R6
        "Agreeableness":        (rev(i[1]) + i[6]) / 2,     # R2, 7
        "Conscientiousness":    (i[2] + rev(i[7])) / 2,     # 3, R8
        "EmotionalStability":   (rev(i[3]) + i[8]) / 2,     # R4, 9
        "Openness":             (i[4] + rev(i[9])) / 2,     # 5, R10
    }


def score_nars(row: dict) -> float | None:
    """QID89_1..4  on 1..5.  Item 1 ('uneasy') is negatively keyed.
    Higher total => more positive attitude toward robots with emotions."""
    items = [likert_to_int(row.get(f"QID89_{i}", "")) for i in range(1, 5)]
    if any(v is None for v in items):
        return None
    # Reverse item 1, then average
    items[0] = 6 - items[0]
    return sum(items) / 4.0


# ---- correlation grid helper ----
def run_grid(pair_rows, subj_cols, obj_cols, label):
    grid, pvals = [], []
    for s in subj_cols:
        for o in obj_cols:
            xs = [r[s] for r in pair_rows]
            ys = [r[o] for r in pair_rows]
            rho, n = spearman(xs, ys)
            p = spearman_p_two_sided(rho, n)
            grid.append({"group": label, "subjective": s, "objective": o,
                         "n": n, "rho": rho, "p": p})
            pvals.append(p)
    for g, q in zip(grid, bh_fdr(pvals)):
        g["q_BH"] = q
    return grid


def main():
    # --- subjective structures reused from Decision A ---
    codes, humans, rows = read_survey()
    posts = {r["ResponseId"]: r for r in rows}

    mapping = list(csv.DictReader(MAPPING_CSV.open("r", encoding="utf-8")))
    latency = read_latency()

    BF = ["Extraversion", "Agreeableness", "Conscientiousness",
          "EmotionalStability", "Openness"]

    pair_rows = []
    for m in mapping:
        sid, rid = m["session_id"], m["post_rid"]
        post = posts.get(rid)
        if post is None:
            continue

        tipi_self = score_tipi(post, "QID108_")
        tipi_bot = score_tipi(post, "QID99_")
        nars = score_nars(post)

        # UX + TLX subscale means (reuse exact logic from Decision A)
        subj = {}
        for grp, members in LIKERT_GROUPS.items():
            subj[grp] = compute_subscale(post, members)
        for grp, members in NASA_TLX_GROUPS.items():
            subj[grp] = compute_subscale(post, members)

        chat_path = find_chat(sid)
        chat_feats = (extract_chat_features(chat_path) if chat_path
                      else {k: None for k in ("n_user_turns", "n_bot_turns",
                                               "user_words_total",
                                               "user_words_per_turn",
                                               "bot_words_per_turn",
                                               "session_duration_s")})
        lat = latency.get(sid, {})
        for k in ("lat_n_turns", "lat_mean_s", "lat_median_s", "lat_sd_s"):
            lat.setdefault(k, None)

        row = {"n": len(pair_rows) + 1, "session_id": sid, "post_rid": rid,
               "NARS": nars}
        for b in BF:
            row[f"self_{b}"] = tipi_self[b]
            row[f"bot_{b}"] = tipi_bot[b]
        row.update(subj)
        row.update(chat_feats)
        row.update(lat)
        pair_rows.append(row)

    if not pair_rows:
        print("no pairs!")
        return

    # write raw per-pair data
    fn = list(pair_rows[0].keys())
    with (OUT_DIR / "personality_pair_data.csv").open("w", encoding="utf-8",
                                                      newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn)
        w.writeheader()
        w.writerows(pair_rows)

    # --- analyses ---
    subj_ux = list(LIKERT_GROUPS.keys())
    subj_tlx = list(NASA_TLX_GROUPS.keys())
    obj_cols = ["session_duration_s", "n_user_turns", "user_words_per_turn",
                "bot_words_per_turn", "lat_median_s", "lat_mean_s"]
    all_rhs = subj_ux + subj_tlx + obj_cols    # right-hand side variables

    # B: self-TIPI grid
    self_cols = [f"self_{b}" for b in BF]
    grid_self = run_grid(pair_rows, self_cols, all_rhs, "self_TIPI")
    # C: robot-TIPI grid
    bot_cols = [f"bot_{b}" for b in BF]
    grid_bot = run_grid(pair_rows, bot_cols, all_rhs, "robot_TIPI")
    # D: self <-> robot same-trait alignment
    grid_selfbot = []
    pvals_sb = []
    for b in BF:
        xs = [r[f"self_{b}"] for r in pair_rows]
        ys = [r[f"bot_{b}"] for r in pair_rows]
        rho, n = spearman(xs, ys)
        p = spearman_p_two_sided(rho, n)
        grid_selfbot.append({"group": "self_x_robot", "subjective": f"self_{b}",
                             "objective": f"bot_{b}", "n": n, "rho": rho, "p": p})
        pvals_sb.append(p)
    for g, q in zip(grid_selfbot, bh_fdr(pvals_sb)):
        g["q_BH"] = q
    # E: NARS grid
    grid_nars = run_grid(pair_rows, ["NARS"], all_rhs, "NARS")

    all_grid = grid_self + grid_bot + grid_selfbot + grid_nars
    with (OUT_DIR / "personality_alignment.csv").open("w", encoding="utf-8",
                                                      newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_grid[0].keys()))
        w.writeheader()
        for g in all_grid:
            out = dict(g)
            for k in ("rho", "p", "q_BH"):
                v = out[k]
                out[k] = "" if isinstance(v, float) and math.isnan(v) \
                    else f"{v:.4f}"
            w.writerow(out)

    # --- narrative summary ---
    lines = []
    lines.append(f"Personality alignment analysis  (N={len(pair_rows)})\n")

    # descriptives
    def desc(col, label):
        vals = [r[col] for r in pair_rows if isinstance(r[col], (int, float))
                and not (isinstance(r[col], float) and math.isnan(r[col]))]
        if not vals:
            return f"{label:30s}  n=0"
        import statistics
        mean = statistics.mean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        return (f"{label:30s}  n={len(vals):>2d}  mean={mean:>5.2f}  "
                f"sd={sd:>5.2f}  range=[{min(vals):.2f}, {max(vals):.2f}]")

    lines.append("--- Self-TIPI (1..7) ---")
    for b in BF:
        lines.append(desc(f"self_{b}", f"self_{b}"))
    lines.append("\n--- Robot-TIPI (1..7) ---")
    for b in BF:
        lines.append(desc(f"bot_{b}", f"bot_{b}"))
    lines.append("\n--- NARS-emotion (reverse-scored mean, 1..5) ---")
    lines.append(desc("NARS", "NARS"))

    # top hits per block
    def top_hits(grid, k=5, title=""):
        lines.append(f"\n--- Top-{k} by raw p : {title} ---")
        lines.append(f"{'subj':22s} {'obj':22s} {'n':>3s} {'rho':>6s} "
                     f"{'p':>8s} {'q_BH':>8s}")
        sg = sorted(grid, key=lambda g: (math.isnan(g["p"]), g["p"]))
        for g in sg[:k]:
            lines.append(f"{g['subjective']:22s} {g['objective']:22s} "
                         f"{g['n']:>3d} {g['rho']:>6.2f} "
                         f"{g['p']:>8.4f} {g['q_BH']:>8.4f}")

    top_hits(grid_self, 8, "self-TIPI x (UX + TLX + objective)")
    top_hits(grid_bot, 8, "robot-TIPI x (UX + TLX + objective)")
    top_hits(grid_selfbot, 5, "self-TIPI x robot-TIPI (same-trait)")
    top_hits(grid_nars, 5, "NARS x (UX + TLX + objective)")

    # FDR survivors per block
    def count_sig(grid, label):
        raw = sum(1 for g in grid if not math.isnan(g["p"]) and g["p"] < 0.05)
        fdr = sum(1 for g in grid if not math.isnan(g["q_BH"]) and g["q_BH"] < 0.05)
        lines.append(f"{label:40s}  raw p<.05: {raw}   BH-FDR q<.05: {fdr}")
    lines.append("\n--- FDR survivors per block ---")
    count_sig(grid_self, "self_TIPI")
    count_sig(grid_bot, "robot_TIPI")
    count_sig(grid_selfbot, "self_x_robot same-trait")
    count_sig(grid_nars, "NARS")

    (OUT_DIR / "personality_summary.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    # --- plots ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        # heatmaps
        def heatmap(grid, row_cols, col_cols, fname, title):
            m = [[float("nan")] * len(col_cols) for _ in row_cols]
            sig = [[""] * len(col_cols) for _ in row_cols]
            for g in grid:
                if g["subjective"] not in row_cols or g["objective"] not in col_cols:
                    continue
                i = row_cols.index(g["subjective"])
                j = col_cols.index(g["objective"])
                m[i][j] = g["rho"]
                if not math.isnan(g["p"]):
                    if g["p"] < .001:
                        sig[i][j] = "***"
                    elif g["p"] < .01:
                        sig[i][j] = "**"
                    elif g["p"] < .05:
                        sig[i][j] = "*"
                    elif g["p"] < .10:
                        sig[i][j] = "."
            fig, ax = plt.subplots(figsize=(10, 4.5))
            im = ax.imshow(m, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
            ax.set_xticks(range(len(col_cols)))
            ax.set_xticklabels(col_cols, rotation=40, ha="right", fontsize=8)
            ax.set_yticks(range(len(row_cols)))
            ax.set_yticklabels([c.split("_", 1)[1] for c in row_cols])
            for i in range(len(row_cols)):
                for j in range(len(col_cols)):
                    v = m[i][j]
                    if not math.isnan(v):
                        ax.text(j, i, f"{v:.2f}{sig[i][j]}",
                                ha="center", va="center", fontsize=8,
                                color=("white" if abs(v) > .55 else "black"))
            ax.set_title(title)
            fig.colorbar(im, ax=ax).set_label(r"Spearman $\rho$")
            fig.tight_layout()
            fig.savefig(OUT_DIR / fname, dpi=150)
            plt.close(fig)

        heatmap(grid_self, self_cols, all_rhs,
                "personality_heatmap_user.png",
                f"Self-TIPI (user Big-Five) vs UX+TLX+objective  (N={len(pair_rows)})")
        heatmap(grid_bot, bot_cols, all_rhs,
                "personality_heatmap_robot.png",
                f"Robot-TIPI (perceived robot Big-Five) vs UX+TLX+objective  (N={len(pair_rows)})")

        # self-robot scatter (5 panels)
        fig, axes = plt.subplots(1, 5, figsize=(15, 3.1))
        for ax, b, g in zip(axes, BF, grid_selfbot):
            xs = [r[f"self_{b}"] for r in pair_rows if
                  isinstance(r[f"self_{b}"], (int, float))
                  and isinstance(r[f"bot_{b}"], (int, float))]
            ys = [r[f"bot_{b}"] for r in pair_rows if
                  isinstance(r[f"self_{b}"], (int, float))
                  and isinstance(r[f"bot_{b}"], (int, float))]
            ax.scatter(xs, ys, alpha=0.75)
            ax.plot([1, 7], [1, 7], "k--", lw=0.6, alpha=0.5)
            ax.set_xlim(1, 7); ax.set_ylim(1, 7)
            ax.set_xlabel(f"self {b[:6]}")
            if ax is axes[0]:
                ax.set_ylabel("robot-perceived")
            rho = g["rho"]
            p = g["p"]
            ax.set_title(f"{b}\n" + (
                f"$\\rho$={rho:.2f}, $p$={p:.2f}" if not math.isnan(rho)
                else "n/a"), fontsize=9)
        fig.suptitle(f"Self vs perceived-robot Big-Five  (N={len(pair_rows)})",
                     y=1.04)
        fig.tight_layout()
        fig.savefig(OUT_DIR / "personality_selfrobot_scatter.png",
                    dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        print(f"plotting failed: {e}")

    print((OUT_DIR / "personality_summary.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
