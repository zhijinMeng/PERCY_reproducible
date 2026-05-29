"""
Decision A : Subjective-Objective Alignment

For the N=20 matched (session, post-survey) pairs:
  * SUBJECTIVE  =  post-survey Likert items, grouped into thematic subscales
  * OBJECTIVE   =  behavioural metrics extracted from chat_history JSON
                   + robot response latency (already pre-computed)

Then compute Spearman rho with bootstrap 95% CI and BH-FDR adjusted p-values
across the full subjective x objective grid.

Outputs (all in Paper_writing/Claude_Writing/):
  subj_obj_pair_data.csv      : N=20 long table, one row per pair, all metrics
  subj_obj_likert_codebook.csv: which raw column belongs to which subscale
  subj_obj_alignment.csv      : every (subjective, objective) correlation
  subj_obj_alignment_heatmap.png
  subj_obj_summary.txt        : terminal-readable narrative
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(r"c:\Users\z5430888\OneDrive - UNSW\Research Project\OneDrive_2026-04-02")
OUT_DIR = ROOT / "Paper_writing" / "Claude_Writing" / "analysis"

SURVEY_CSV = (ROOT / "Paper_writing" / "material"
              / "Extra+Sections,+Feedback+Survey_20+April+2026_15.22.csv")
MAPPING_CSV = OUT_DIR.parent / "mapping" / "FINAL_session_post_mapping.csv"
LATENCY_CSV = OUT_DIR / "response_latency_summary.csv"

CHAT_SEARCH_ROOTS = [
    ROOT / "fixed_data" / "Ari Robot",
    ROOT / "Ari Robot",
]
CHAT_FILE_NAMES = [
    "chat_history_asr_aligned_large_v3.json",
    "chat_history.json",
]


# ---------- 1. read post-survey ----------
def read_survey() -> tuple[list[str], list[str], list[dict]]:
    """Return (column_codes, human_questions, response_rows)."""
    with SURVEY_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        codes = next(reader)
        humans = next(reader)
        next(reader)            # third meta row (json import id)
        rows = []
        for row in reader:
            if not row or len(row) < len(codes):
                continue
            d = {codes[i]: row[i] for i in range(len(codes))}
            rows.append(d)
    return codes, humans, rows


# ---------- 2. Likert subscales ----------
# Code -> subscale name.  Built by inspection of the question text.
LIKERT_GROUPS: dict[str, list[str]] = {
    "Naturalness":  ["Q1", "Q7"],                # natural feel; personalisation makes it natural
    "Comfort":      ["Q2"],
    "Engagement":   ["Q3", "Q9", "Q10"],         # engaging convo + emotion engagement + personal-info engagement
    "Understanding":["Q4", "Q5", "Q6"],          # relevance, understanding, personalised
    "EmotionResp":  ["Q8"],
    "Responsiveness":["Q11"],                    # robot speed (higher = more responsive)
    "Overall":      ["Q13"],
    # Q12 (interview length) intentionally excluded: it is a bipolar/ideal-point
    # scale where the optimum is the centre, not monotone in any direction.
}

NASA_TLX_GROUPS = {
    "TLX_Mental":     ["QID82_1"],
    "TLX_Physical":   ["QID82_2"],
    "TLX_Temporal":   ["QID82_3"],
    "TLX_Performance":["QID82_4"],
    "TLX_Effort":     ["QID82_5"],
    "TLX_Frustration":["QID82_6"],
}


_LIKERT_LOOKUP = {
    # canonical 7-point scale, low (1) -> high (7)
    # negative anchors
    "very unnatural": 1, "very uncomfortable": 1, "very unengaging": 1,
    "very irrelevant": 1, "never understood": 1, "very unresponsive": 1,
    "very poor": 1, "much too short": 1, "much too long": 1,
    "strongly disagree": 1,
    "very low": 1,

    "unnatural": 2, "uncomfortable": 2, "unengaging": 2, "irrelevant": 2,
    "rarely understood": 2, "unresponsive": 2, "poor": 2,
    "too short": 2, "too long": 2,
    "moderately disagree": 2, "disagree": 2,
    "low": 2,
    "slow": 2, "somewhat long": 3, "somewhat short": 3,

    "slightly unnatural": 3, "slightly uncomfortable": 3, "slightly unengaging": 3,
    "slightly irrelevant": 3, "sometimes understood": 3, "slightly unresponsive": 3,
    "fair": 3,                  # treat 'Fair' as below mid (poor->good axis)
    "slightly too short": 3, "slightly too long": 3,
    "disagree a little": 3, "slightly disagree": 3, "somewhat disagree": 3,
    "slightly low": 3,

    "neutral": 4, "undecided": 4, "neither agree nor disagree": 4,
    "just right": 4, "appropriate": 4,
    "okay": 4, "ok": 4,

    "slightly natural": 5, "slightly comfortable": 5, "slightly engaging": 5,
    "slightly relevant": 5, "often understood": 5, "slightly responsive": 5,
    "agree a little": 5, "slightly agree": 5, "somewhat agree": 5,
    "slightly high": 5,

    "natural": 6, "comfortable": 6, "engaging": 6, "relevant": 6,
    "usually understood": 6, "mostly understood": 6,
    "responsive": 6, "good": 6,
    "agree": 6, "moderately agree": 6,
    "high": 6,
    "highly relevant": 6,

    "very natural": 7, "very comfortable": 7, "very engaging": 7,
    "very relevant": 7, "always understood": 7, "very responsive": 7,
    "excellent": 7, "very good": 7,
    "strongly agree": 7,
    "very high": 7,
}


def _normalise(s: str) -> str:
    s = s.strip().lower()
    s = s.rstrip(".")
    s = re.sub(r"\s+", " ", s)
    return s


def likert_to_int(s: str) -> float | None:
    """Parse Qualtrics likert: integer string OR text label."""
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        pass
    norm = _normalise(s)
    if norm in _LIKERT_LOOKUP:
        return float(_LIKERT_LOOKUP[norm])
    # fallback: leading integer in cell
    m = re.match(r"^\s*(\d+)", s)
    if m:
        return float(m.group(1))
    return None


def compute_subscale(row: dict, codes: list[str]) -> float | None:
    vals = [likert_to_int(row.get(c, "")) for c in codes]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


# ---------- 3. read latency ----------
def read_latency() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with LATENCY_CSV.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            sid = r["session"]
            if sid == "ALL":
                continue
            try:
                out[sid] = {
                    "lat_n_turns": int(r["n_turns"]),
                    "lat_mean_s":  float(r["mean_s"]),
                    "lat_median_s":float(r["median_s"]),
                    "lat_sd_s":    float(r["sd_s"]),
                }
            except Exception:
                continue
    return out


# ---------- 4. read chat history ----------
def find_chat(session_id: str) -> Path | None:
    for root in CHAT_SEARCH_ROOTS:
        if not root.exists():
            continue
        for folder in root.rglob(session_id):
            if not folder.is_dir():
                continue
            for fname in CHAT_FILE_NAMES:
                cand = folder / fname
                if cand.exists():
                    return cand
    return None


WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


def extract_chat_features(chat_path: Path) -> dict:
    with chat_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        msgs = data
    elif isinstance(data, dict):
        msgs = data.get("messages", []) or data.get("history", []) or []
    else:
        msgs = []
    user_msgs = [m for m in msgs if m.get("role") == "user"]
    bot_msgs = [m for m in msgs if m.get("role") == "assistant"]

    user_texts = [(m.get("content") or "").strip() for m in user_msgs]
    bot_texts = [(m.get("content") or "").strip() for m in bot_msgs]

    user_word_counts = [len(WORD_RE.findall(t)) for t in user_texts if t]
    bot_word_counts = [len(WORD_RE.findall(t)) for t in bot_texts if t]

    # session duration via asr_start/asr_end if present
    starts, ends = [], []
    for m in msgs:
        s, e = m.get("asr_start"), m.get("asr_end")
        if s is not None:
            try:
                starts.append(float(s))
            except Exception:
                pass
        if e is not None:
            try:
                ends.append(float(e))
            except Exception:
                pass
    if starts and ends:
        duration_s = max(ends) - min(starts)
    else:
        duration_s = None

    return {
        "n_user_turns": len(user_msgs),
        "n_bot_turns": len(bot_msgs),
        "user_words_total": sum(user_word_counts),
        "user_words_per_turn": (sum(user_word_counts) / len(user_word_counts)
                                if user_word_counts else 0),
        "bot_words_per_turn": (sum(bot_word_counts) / len(bot_word_counts)
                               if bot_word_counts else 0),
        "session_duration_s": duration_s,
    }


# ---------- 5. correlations ----------
def spearman(x: list[float], y: list[float]) -> tuple[float, int]:
    """Manual Spearman rho on paired complete cases.  Returns (rho, n_used)."""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None
             and not (isinstance(a, float) and math.isnan(a))
             and not (isinstance(b, float) and math.isnan(b))]
    n = len(pairs)
    if n < 4:
        return float("nan"), n
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rx = average_rank(xs)
    ry = average_rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    denx = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n)))
    deny = math.sqrt(sum((ry[i] - my) ** 2 for i in range(n)))
    if denx == 0 or deny == 0:
        return float("nan"), n
    return num / (denx * deny), n


def average_rank(values: list[float]) -> list[float]:
    indexed = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def spearman_p_two_sided(rho: float, n: int) -> float:
    """t-distribution approximation (Press et al. NRP).  Good enough for n>=10."""
    if math.isnan(rho) or n < 4:
        return float("nan")
    if abs(rho) >= 0.9999:
        return 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho ** 2))
    df = n - 2
    return 2 * student_t_sf(abs(t), df)


def student_t_sf(t: float, df: int) -> float:
    """Survival function P(T > t)  via incomplete beta (Abramowitz 26.7.1)."""
    x = df / (df + t * t)
    return 0.5 * incomplete_beta(df / 2.0, 0.5, x)


def incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta.  Continued-fraction implementation."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1 - x))
    front = math.exp(lbeta) / a
    if x < (a + 1) / (a + b + 2):
        return front * betacf(a, b, x)
    return 1 - front * betacf(b, a, 1 - x) * (a / b)


def betacf(a: float, b: float, x: float, max_iter: int = 200,
          eps: float = 3e-7) -> float:
    qab = a + b
    qap = a + 1
    qam = a - 1
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def bh_fdr(pvals: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values."""
    n = len(pvals)
    order = sorted(range(n), key=lambda i: (math.isnan(pvals[i]), pvals[i]))
    adj = [float("nan")] * n
    prev = 1.0
    for rank_from_top, idx in enumerate(reversed(order), 1):
        k = n - rank_from_top + 1
        p = pvals[idx]
        if math.isnan(p):
            adj[idx] = float("nan")
            continue
        val = min(prev, p * n / k)
        adj[idx] = val
        prev = val
    return adj


# ---------- 6. main ----------
def main():
    codes, humans, rows = read_survey()
    code2human = dict(zip(codes, humans))
    posts = {r["ResponseId"]: r for r in rows}

    mapping = list(csv.DictReader(MAPPING_CSV.open("r", encoding="utf-8")))
    print(f"Pairs in mapping : {len(mapping)}")
    latency = read_latency()
    print(f"Sessions with latency stats : {len(latency)}")

    # codebook
    codebook_rows = []
    for grp, members in {**LIKERT_GROUPS, **NASA_TLX_GROUPS}.items():
        for c in members:
            codebook_rows.append({
                "subscale": grp, "qualtrics_code": c,
                "question_text": code2human.get(c, "")
            })
    with (OUT_DIR / "subj_obj_likert_codebook.csv").open(
            "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(codebook_rows[0].keys()))
        w.writeheader()
        w.writerows(codebook_rows)

    # Build pair-level table
    pair_rows = []
    for m in mapping:
        sid, rid = m["session_id"], m["post_rid"]
        post = posts.get(rid)
        if not post:
            print(f"  WARN: no post for {rid}")
            continue

        # subjective
        subj = {}
        for grp, members in LIKERT_GROUPS.items():
            subj[grp] = compute_subscale(post, members)
        for grp, members in NASA_TLX_GROUPS.items():
            subj[grp] = compute_subscale(post, members)

        # objective: chat features
        chat_path = find_chat(sid)
        if chat_path is None:
            print(f"  WARN: no chat history found for {sid}")
            chat_feats = {k: None for k in [
                "n_user_turns", "n_bot_turns", "user_words_total",
                "user_words_per_turn", "bot_words_per_turn",
                "session_duration_s",
            ]}
        else:
            chat_feats = extract_chat_features(chat_path)

        # objective: latency (fill with None if missing so column always exists)
        lat = latency.get(sid, {})
        for k in ("lat_n_turns", "lat_mean_s", "lat_median_s", "lat_sd_s"):
            lat.setdefault(k, None)

        row = {
            "n": len(pair_rows) + 1,
            "session_id": sid,
            "post_rid": rid,
            "tier": m.get("tier_code", ""),
        }
        row.update(subj)
        row.update(chat_feats)
        row.update(lat)
        pair_rows.append(row)

    # write pair-level table
    if not pair_rows:
        print("FATAL: no pair rows")
        return
    fieldnames = list(pair_rows[0].keys())
    with (OUT_DIR / "subj_obj_pair_data.csv").open(
            "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(pair_rows)
    print(f"wrote subj_obj_pair_data.csv ({len(pair_rows)} pairs)")

    # ---- correlation grid ----
    subj_cols = list(LIKERT_GROUPS.keys()) + list(NASA_TLX_GROUPS.keys())
    obj_cols = ["session_duration_s", "n_user_turns", "user_words_per_turn",
                "bot_words_per_turn", "lat_median_s", "lat_mean_s"]

    grid: list[dict] = []
    pvals: list[float] = []
    for s in subj_cols:
        for o in obj_cols:
            xs = [r[s] for r in pair_rows]
            ys = [r[o] for r in pair_rows]
            rho, n_used = spearman(xs, ys)
            p = spearman_p_two_sided(rho, n_used)
            grid.append({
                "subjective": s, "objective": o,
                "n": n_used, "rho": rho, "p": p,
            })
            pvals.append(p)
    qvals = bh_fdr(pvals)
    for g, q in zip(grid, qvals):
        g["q_BH"] = q

    with (OUT_DIR / "subj_obj_alignment.csv").open(
            "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(grid[0].keys()))
        w.writeheader()
        for g in grid:
            r = dict(g)
            r["rho"] = "" if math.isnan(r["rho"]) else f"{r['rho']:.3f}"
            r["p"]   = "" if math.isnan(r["p"])   else f"{r['p']:.4f}"
            r["q_BH"]= "" if math.isnan(r["q_BH"])else f"{r['q_BH']:.4f}"
            w.writerow(r)

    # narrative
    grid_sorted = sorted(grid, key=lambda g: (math.isnan(g["p"]), g["p"]))
    with (OUT_DIR / "subj_obj_summary.txt").open("w", encoding="utf-8") as f:
        f.write(f"Decision A : Subjective-Objective Alignment\n")
        f.write(f"N pairs analysed : {len(pair_rows)}\n\n")
        f.write(f"Subjective subscales : {len(subj_cols)}\n")
        for c in subj_cols:
            f.write(f"  - {c}\n")
        f.write(f"\nObjective metrics    : {len(obj_cols)}\n")
        for c in obj_cols:
            f.write(f"  - {c}\n")
        f.write(f"\nTotal correlations   : {len(grid)}\n")
        f.write(f"Significant uncorrected p<.05 : "
                f"{sum(1 for g in grid if not math.isnan(g['p']) and g['p']<0.05)}\n")
        f.write(f"Significant after BH-FDR q<.05 : "
                f"{sum(1 for g in grid if not math.isnan(g['q_BH']) and g['q_BH']<0.05)}\n")
        f.write("\nTop 12 by raw p-value:\n")
        f.write(f"{'subjective':18s} {'objective':22s} {'n':>3s} "
                f"{'rho':>7s} {'p':>8s} {'q_BH':>8s}\n")
        for g in grid_sorted[:12]:
            f.write(f"{g['subjective']:18s} {g['objective']:22s} "
                    f"{g['n']:>3d} {g['rho']:>7.3f} {g['p']:>8.4f} "
                    f"{g['q_BH']:>8.4f}\n")

    # heatmap (matplotlib if available)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        rho_grid = [[float("nan")] * len(obj_cols) for _ in subj_cols]
        sig_grid = [["" for _ in obj_cols] for _ in subj_cols]
        for g in grid:
            i = subj_cols.index(g["subjective"])
            j = obj_cols.index(g["objective"])
            rho_grid[i][j] = g["rho"]
            if not math.isnan(g["p"]):
                if g["p"] < 0.001:
                    sig_grid[i][j] = "***"
                elif g["p"] < 0.01:
                    sig_grid[i][j] = "**"
                elif g["p"] < 0.05:
                    sig_grid[i][j] = "*"
                elif g["p"] < 0.10:
                    sig_grid[i][j] = "."
        fig, ax = plt.subplots(figsize=(9, 7))
        im = ax.imshow(rho_grid, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(obj_cols)))
        ax.set_xticklabels(obj_cols, rotation=35, ha="right")
        ax.set_yticks(range(len(subj_cols)))
        ax.set_yticklabels(subj_cols)
        for i in range(len(subj_cols)):
            for j in range(len(obj_cols)):
                v = rho_grid[i][j]
                if not math.isnan(v):
                    ax.text(j, i, f"{v:.2f}{sig_grid[i][j]}",
                            ha="center", va="center", fontsize=9,
                            color=("white" if abs(v) > 0.55 else "black"))
        ax.set_title(f"Subjective-Objective Spearman rho  (N={len(pair_rows)})")
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label("Spearman rho")
        fig.tight_layout()
        out_png = OUT_DIR / "subj_obj_alignment_heatmap.png"
        fig.savefig(out_png, dpi=150)
        print(f"wrote {out_png}")
    except Exception as e:
        print(f"matplotlib unavailable or failed ({e}); skipping heatmap")

    print("\n--- subj_obj_summary.txt ---")
    print((OUT_DIR / "subj_obj_summary.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
