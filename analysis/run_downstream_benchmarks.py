#!/usr/bin/env python3
"""Run Benchmark A/B with grouped CV and CI.

Data: MERCI normalized sessions discovered by `iter_normalized_sessions()`.
Evaluation: session-level GroupKFold (5 folds) + bootstrap confidence intervals.
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import GroupKFold
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score

from merci_message_io import EMOTIONS
from merci_normalized_media import iter_normalized_sessions, load_session_messages

OUT_DIR = Path(__file__).parent
MODEL_SEEDS = [11, 22, 33]
N_FOLDS = 5
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 42

VISUAL_POSITIVE = {"happy"}
VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}
EMOTION_LIST = sorted(EMOTIONS)
FER_PROB_COLS = [f"fer_p_{e}" for e in EMOTION_LIST]


def classify_valence_conflict(emotion: str, sentiment: str) -> str:
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


@dataclass
class TurnRow:
    session_id: str
    message_index: int
    text: str
    emotion: str
    sentiment: str
    is_conflict: int
    cross_modal_class: str
    visual_valence: str
    fer_prob: np.ndarray | None = None


def load_offline_fer_probs() -> dict[tuple[str, int], np.ndarray]:
    path = OUT_DIR / "offline_fer_probs.csv"
    if not path.exists():
        return {}
    out: dict[tuple[str, int], np.ndarray] = {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            sid = str(r.get("session_id", "")).strip()
            try:
                midx = int(r.get("message_index", -1))
            except (TypeError, ValueError):
                continue
            vec = np.array([float(r.get(c, 0.0) or 0.0) for c in FER_PROB_COLS], dtype=float)
            s = float(vec.sum())
            if s > 0:
                vec = vec / s
            out[(sid, midx)] = vec
    return out


def build_turn_table() -> list[TurnRow]:
    audited_sessions: set[str] | None = None
    audited_csv = OUT_DIR / "cross_modal_per_session.csv"
    if audited_csv.exists():
        with audited_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            audited_sessions = {str(r.get("session_id", "")).strip() for r in reader if r.get("session_id")}
    fer_lookup = load_offline_fer_probs()
    rows: list[TurnRow] = []
    for sid, session_dir in iter_normalized_sessions():
        if audited_sessions is not None and sid not in audited_sessions:
            continue
        messages = load_session_messages(session_dir)
        for msg in messages:
            if msg.get("role") != "user":
                continue
            em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            sn = str(msg.get("sentiment") or "").lower().strip()
            text = str(msg.get("content") or "").strip()
            if em not in EMOTIONS or sn not in {"positive", "neutral", "negative"} or not text:
                continue
            cls = classify_valence_conflict(em, sn)
            if em == "happy":
                vv = "positive"
            elif em in VISUAL_NEGATIVE:
                vv = "negative"
            elif em == "neutral":
                vv = "neutral"
            else:
                vv = "ambiguous"
            is_conflict = int(cls == "conflict")
            try:
                midx = int(msg.get("message_index", -1))
            except (TypeError, ValueError):
                midx = -1
            fer_prob = fer_lookup.get((sid, midx))
            if fer_prob is None and fer_lookup:
                fer_prob = np.zeros(len(EMOTION_LIST), dtype=float)
                fer_prob[EMOTION_LIST.index("neutral")] = 1.0
            rows.append(
                TurnRow(
                    session_id=sid,
                    message_index=midx,
                    text=text,
                    emotion=em,
                    sentiment=sn,
                    is_conflict=is_conflict,
                    cross_modal_class=cls,
                    visual_valence=vv,
                    fer_prob=fer_prob,
                )
            )
    return rows


def macro_f1(y_true, y_pred, labels=None) -> float:
    return float(f1_score(y_true, y_pred, average="macro", labels=labels, zero_division=0))


def binary_conflict_f1(y_true, y_pred) -> float:
    return float(f1_score(y_true, y_pred, pos_label=1, zero_division=0))


def session_conflict_f1_std(rows: list[TurnRow], y_true: np.ndarray, y_pred: np.ndarray) -> float:
    by_session: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r, yt, yp in zip(rows, y_true, y_pred):
        by_session[r.session_id].append((int(yt), int(yp)))
    f1s: list[float] = []
    for pairs in by_session.values():
        yt = [p[0] for p in pairs]
        yp = [p[1] for p in pairs]
        if sum(yt) == 0 and sum(yp) == 0:
            continue
        f1s.append(binary_conflict_f1(yt, yp))
    return float(np.std(f1s)) if f1s else float("nan")


def stat(vals: list[float]) -> tuple[float, float]:
    arr = np.array(vals, dtype=float)
    return float(np.mean(arr)), float(np.std(arr))


def _bootstrap_group_metric(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    groups: np.ndarray,
    metric_fn,
    b: int = BOOTSTRAP_B,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    unique_groups = np.array(sorted(set(groups.tolist())))
    by_group = {g: np.where(groups == g)[0] for g in unique_groups}
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(b):
        sampled = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        idx = np.concatenate([by_group[g] for g in sampled])
        vals.append(float(metric_fn(y_true[idx], y_pred[idx])))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def _run_groupkfold_predictions(
    rows: list[TurnRow],
    labels: np.ndarray,
    model_seed: int,
    *,
    add_visual_valence: bool = False,
    add_fer_probs: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    texts = np.array([r.text for r in rows])
    groups = np.array([r.session_id for r in rows])
    valence = np.array([r.visual_valence for r in rows])
    fer_probs = np.array(
        [
            (r.fer_prob if r.fer_prob is not None else np.full(len(EMOTION_LIST), np.nan))
            for r in rows
        ],
        dtype=float,
    )
    y = labels
    y_pred = np.empty(len(rows), dtype=object)
    y_score = np.full(len(rows), np.nan, dtype=float)
    gkf = GroupKFold(n_splits=N_FOLDS)

    for tr_idx, te_idx in gkf.split(texts, y, groups=groups):
        vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=1)
        X_tr = vec.fit_transform(texts[tr_idx])
        X_te = vec.transform(texts[te_idx])
        if add_visual_valence:
            vv_vocab = ["positive", "neutral", "negative", "ambiguous"]
            vmap = {v: i for i, v in enumerate(vv_vocab)}
            tr_dense = np.zeros((len(tr_idx), len(vv_vocab)), dtype=float)
            te_dense = np.zeros((len(te_idx), len(vv_vocab)), dtype=float)
            for i, v in enumerate(valence[tr_idx]):
                tr_dense[i, vmap.get(v, 3)] = 1.0
            for i, v in enumerate(valence[te_idx]):
                te_dense[i, vmap.get(v, 3)] = 1.0
            X_tr = hstack([X_tr, csr_matrix(tr_dense)], format="csr")
            X_te = hstack([X_te, csr_matrix(te_dense)], format="csr")
        if add_fer_probs:
            X_tr = hstack([X_tr, csr_matrix(fer_probs[tr_idx])], format="csr")
            X_te = hstack([X_te, csr_matrix(fer_probs[te_idx])], format="csr")

        clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=model_seed)
        clf.fit(X_tr, y[tr_idx])
        pred = clf.predict(X_te)
        y_pred[te_idx] = pred

        if len(np.unique(y)) == 2:
            probs = clf.predict_proba(X_te)
            classes = list(clf.classes_)
            pos_i = classes.index(1)
            y_score[te_idx] = probs[:, pos_i]
    return y_pred, y_score


def run_benchmark_a(rows: list[TurnRow]) -> list[dict]:
    y_true = np.array([r.is_conflict for r in rows], dtype=int)
    groups = np.array([r.session_id for r in rows])
    majority = int(np.mean(y_true) >= 0.5)
    y_maj = np.full_like(y_true, majority)

    results: list[dict] = []
    macro = macro_f1(y_true, y_maj, labels=[0, 1])
    c_f1 = binary_conflict_f1(y_true, y_maj)
    pr_auc = average_precision_score(y_true, y_maj) if len(np.unique(y_true)) > 1 else float("nan")
    m_ci = _bootstrap_group_metric(
        y_true, y_maj, groups, lambda a, b: macro_f1(a, b, labels=[0, 1])
    )
    c_ci = _bootstrap_group_metric(y_true, y_maj, groups, binary_conflict_f1)
    p_ci = _bootstrap_group_metric(y_true, y_maj, groups, average_precision_score)
    results.append(
        {
            "model": "Majority baseline",
            "macro_f1": macro,
            "macro_f1_ci_low": m_ci[0],
            "macro_f1_ci_high": m_ci[1],
            "conflict_f1": c_f1,
            "conflict_f1_ci_low": c_ci[0],
            "conflict_f1_ci_high": c_ci[1],
            "pr_auc": pr_auc,
            "pr_auc_ci_low": p_ci[0],
            "pr_auc_ci_high": p_ci[1],
        }
    )

    pred_all: list[np.ndarray] = []
    score_all: list[np.ndarray] = []
    for seed in MODEL_SEEDS:
        pred, score = _run_groupkfold_predictions(rows, y_true, seed, add_visual_valence=False)
        pred_all.append(pred.astype(int))
        score_all.append(score.astype(float))
    y_pred = np.rint(np.mean(np.vstack(pred_all), axis=0)).astype(int)
    y_score = np.nanmean(np.vstack(score_all), axis=0)
    macro = macro_f1(y_true, y_pred, labels=[0, 1])
    c_f1 = binary_conflict_f1(y_true, y_pred)
    pr_auc = average_precision_score(y_true, y_score)
    m_ci = _bootstrap_group_metric(
        y_true, y_pred, groups, lambda a, b: macro_f1(a, b, labels=[0, 1])
    )
    c_ci = _bootstrap_group_metric(y_true, y_pred, groups, binary_conflict_f1)
    p_ci = _bootstrap_group_metric(y_true, y_pred, groups, average_precision_score)
    results.append(
        {
            "model": "LogReg + TF-IDF (5-fold CV)",
            "macro_f1": macro,
            "macro_f1_ci_low": m_ci[0],
            "macro_f1_ci_high": m_ci[1],
            "conflict_f1": c_f1,
            "conflict_f1_ci_low": c_ci[0],
            "conflict_f1_ci_high": c_ci[1],
            "pr_auc": pr_auc,
            "pr_auc_ci_low": p_ci[0],
            "pr_auc_ci_high": p_ci[1],
        }
    )
    return results


def run_benchmark_b(rows: list[TurnRow]) -> list[dict]:
    fer_lookup = load_offline_fer_probs()
    class_order = ["consistent", "neutral", "conflict", "other"]
    y_true = np.array([r.cross_modal_class for r in rows], dtype=object)
    y_bin_true = np.array([int(v == "conflict") for v in y_true], dtype=int)
    groups = np.array([r.session_id for r in rows])
    results: list[dict] = []

    vals, counts = np.unique(y_true, return_counts=True)
    maj = vals[int(np.argmax(counts))]
    y_maj = np.full(len(y_true), maj)
    full_f1 = macro_f1(y_true, y_maj, labels=class_order)
    conf_f1 = binary_conflict_f1(y_bin_true, np.array([int(v == "conflict") for v in y_maj]))
    full_ci = _bootstrap_group_metric(
        y_true, y_maj, groups, lambda a, b: macro_f1(a, b, labels=class_order)
    )
    conf_ci = _bootstrap_group_metric(
        y_bin_true,
        np.array([int(v == "conflict") for v in y_maj]),
        groups,
        binary_conflict_f1,
    )
    results.append(
        {
            "model": "Majority baseline",
            "full_macro_f1": full_f1,
            "full_macro_f1_ci_low": full_ci[0],
            "full_macro_f1_ci_high": full_ci[1],
            "conflict_f1": conf_f1,
            "conflict_f1_ci_low": conf_ci[0],
            "conflict_f1_ci_high": conf_ci[1],
        }
    )

    pred_text_runs: list[np.ndarray] = []
    for seed in MODEL_SEEDS:
        pred_text, _ = _run_groupkfold_predictions(rows, y_true, seed, add_visual_valence=False)
        pred_text_runs.append(pred_text.astype(object))

    has_fer = bool(fer_lookup) and all(r.fer_prob is not None for r in rows)
    pred_mm_runs: list[np.ndarray] = []
    if has_fer:
        for seed in MODEL_SEEDS:
            pred_mm, _ = _run_groupkfold_predictions(
                rows, y_true, seed, add_visual_valence=False, add_fer_probs=True
            )
            pred_mm_runs.append(pred_mm.astype(object))

    def majority_vote(stacked: np.ndarray) -> np.ndarray:
        out = []
        for col in stacked.T:
            vals, cnt = np.unique(col, return_counts=True)
            out.append(vals[int(np.argmax(cnt))])
        return np.array(out, dtype=object)

    y_pred_text = majority_vote(np.vstack(pred_text_runs))

    full_text = macro_f1(y_true, y_pred_text, labels=class_order)
    conf_text = binary_conflict_f1(y_bin_true, np.array([int(v == "conflict") for v in y_pred_text]))
    full_ci = _bootstrap_group_metric(
        y_true, y_pred_text, groups, lambda a, b: macro_f1(a, b, labels=class_order)
    )
    conf_ci = _bootstrap_group_metric(
        y_bin_true,
        np.array([int(v == "conflict") for v in y_pred_text]),
        groups,
        binary_conflict_f1,
    )
    results.append(
        {
            "model": "Text-only LogReg (5-fold CV)",
            "full_macro_f1": full_text,
            "full_macro_f1_ci_low": full_ci[0],
            "full_macro_f1_ci_high": full_ci[1],
            "conflict_f1": conf_text,
            "conflict_f1_ci_low": conf_ci[0],
            "conflict_f1_ci_high": conf_ci[1],
        }
    )

    if pred_mm_runs:
        y_pred_mm = majority_vote(np.vstack(pred_mm_runs))
        full_mm = macro_f1(y_true, y_pred_mm, labels=class_order)
        conf_mm = binary_conflict_f1(y_bin_true, np.array([int(v == "conflict") for v in y_pred_mm]))
        full_ci = _bootstrap_group_metric(
            y_true, y_pred_mm, groups, lambda a, b: macro_f1(a, b, labels=class_order)
        )
        conf_ci = _bootstrap_group_metric(
            y_bin_true,
            np.array([int(v == "conflict") for v in y_pred_mm]),
            groups,
            binary_conflict_f1,
        )
        results.append(
            {
                "model": "Text + raw FER probs (5-fold CV)",
                "full_macro_f1": full_mm,
                "full_macro_f1_ci_low": full_ci[0],
                "full_macro_f1_ci_high": full_ci[1],
                "conflict_f1": conf_mm,
                "conflict_f1_ci_low": conf_ci[0],
                "conflict_f1_ci_high": conf_ci[1],
            }
        )
    return results


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    all_rows = build_turn_table()
    session_ids = sorted({r.session_id for r in all_rows})
    n_conflict = sum(r.is_conflict for r in all_rows)
    group_counts = defaultdict(int)
    group_pos = defaultdict(int)
    for r in all_rows:
        group_counts[r.session_id] += 1
        group_pos[r.session_id] += r.is_conflict
    gkf = GroupKFold(n_splits=N_FOLDS)
    groups = np.array([r.session_id for r in all_rows])
    y = np.array([r.is_conflict for r in all_rows])
    fold_summary = []
    for i, (_, te) in enumerate(gkf.split(np.zeros(len(all_rows)), y, groups=groups), start=1):
        n = int(len(te))
        p = int(y[te].sum())
        fold_summary.append({"fold": i, "n_turns": n, "n_conflict": p, "conflict_rate": p / n if n else 0.0})

    summary = {
        "data_root": str(iter_normalized_sessions()[0][1].parent) if session_ids else "",
        "model_seeds": MODEL_SEEDS,
        "n_folds": N_FOLDS,
        "bootstrap_b": BOOTSTRAP_B,
        "n_sessions": len(session_ids),
        "n_user_turns": len(all_rows),
        "n_conflict": n_conflict,
        "conflict_rate": n_conflict / len(all_rows) if all_rows else 0.0,
        "fold_summary": fold_summary,
        "benchmark_a_conflict_prediction": run_benchmark_a(all_rows),
        "benchmark_b_conflict_aware_emotion": run_benchmark_b(all_rows),
    }

    out_json = OUT_DIR / "downstream_benchmark_results.json"
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_csv(OUT_DIR / "benchmark_a_conflict_prediction.csv", summary["benchmark_a_conflict_prediction"])
    write_csv(OUT_DIR / "benchmark_b_conflict_aware_emotion.csv", summary["benchmark_b_conflict_aware_emotion"])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
