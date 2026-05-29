#!/usr/bin/env python3
"""Minimal cross-corpus benchmark: MERCI vs MELD (valence-3, text-only).

Usage:
  .venv-analysis/bin/python run_cross_corpus_merci_meld.py \
    --meld-train /path/to/train_sent_emo.csv \
    --meld-dev /path/to/dev_sent_emo.csv \
    --meld-test /path/to/test_sent_emo.csv

If MELD paths are omitted or missing, the script still computes MERCI in-domain
5-fold CV results and writes a TODO note for MELD transfer.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold

from merci_message_io import EMOTIONS
from merci_normalized_media import iter_normalized_sessions, load_session_messages

OUT_DIR = Path(__file__).parent
N_FOLDS = 5
BOOT_B = 2000
BOOT_SEED = 42

VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}
VALENCE_ORDER = ["negative", "neutral", "positive"]
MELD_TO_VALENCE = {
    "anger": "negative",
    "disgust": "negative",
    "fear": "negative",
    "sadness": "negative",
    "neutral": "neutral",
    "joy": "positive",
    "surprise": "positive",
}
IEMOCAP_TO_VALENCE = {
    "ang": "negative",
    "sad": "negative",
    "fru": "negative",
    "fea": "negative",
    "dis": "negative",
    "neu": "neutral",
    "hap": "positive",
    "exc": "positive",
    "sur": "positive",
}


@dataclass
class MerciRow:
    session_id: str
    text: str
    valence: str
    cross_modal_class: str


def classify_valence_conflict(emotion: str, sentiment: str) -> str:
    if emotion == "neutral" or sentiment == "neutral":
        return "neutral"
    if emotion == "happy" and sentiment == "positive":
        return "consistent"
    if emotion in VISUAL_NEGATIVE and sentiment == "negative":
        return "consistent"
    if emotion == "happy" and sentiment == "negative":
        return "conflict"
    if emotion in VISUAL_NEGATIVE and sentiment == "positive":
        return "conflict"
    return "other"


def load_merci_rows() -> list[MerciRow]:
    audited_csv = OUT_DIR / "cross_modal_per_session.csv"
    audited_sessions: set[str] | None = None
    if audited_csv.exists():
        with audited_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            audited_sessions = {str(r.get("session_id", "")).strip() for r in reader if r.get("session_id")}

    rows: list[MerciRow] = []
    for sid, session_dir in iter_normalized_sessions():
        if audited_sessions is not None and sid not in audited_sessions:
            continue
        for msg in load_session_messages(session_dir):
            if msg.get("role") != "user":
                continue
            em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            sn = str(msg.get("sentiment") or "").lower().strip()
            text = str(msg.get("content") or "").strip()
            if em not in EMOTIONS or sn not in {"positive", "neutral", "negative"} or not text:
                continue
            rows.append(
                MerciRow(
                    session_id=sid,
                    text=text,
                    valence=sn,
                    cross_modal_class=classify_valence_conflict(em, sn),
                )
            )
    return rows


def macro_f1(y_true, y_pred) -> float:
    return float(f1_score(y_true, y_pred, average="macro", labels=VALENCE_ORDER, zero_division=0))


def bootstrap_ci_by_session(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    session_ids: np.ndarray,
    *,
    mask: np.ndarray | None = None,
    b: int = BOOT_B,
    seed: int = BOOT_SEED,
) -> tuple[float | None, float | None]:
    if mask is not None:
        y_true = y_true[mask]
        y_pred = y_pred[mask]
        session_ids = session_ids[mask]
    if len(y_true) == 0:
        return None, None
    uniq = np.array(sorted(set(session_ids.tolist())))
    by_sid = {sid: np.where(session_ids == sid)[0] for sid in uniq}
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(b):
        sampled = rng.choice(uniq, size=len(uniq), replace=True)
        idx = np.concatenate([by_sid[sid] for sid in sampled])
        vals.append(macro_f1(y_true[idx], y_pred[idx]))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def eval_in_domain_merci(rows: list[MerciRow]) -> dict:
    X = np.array([r.text for r in rows])
    y = np.array([r.valence for r in rows], dtype=object)
    groups = np.array([r.session_id for r in rows], dtype=object)
    strata = np.array([r.cross_modal_class for r in rows], dtype=object)
    pred = np.empty(len(rows), dtype=object)
    gkf = GroupKFold(n_splits=N_FOLDS)
    for tr, te in gkf.split(X, y, groups=groups):
        vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=1)
        X_tr = vec.fit_transform(X[tr])
        X_te = vec.transform(X[te])
        clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)
        clf.fit(X_tr, y[tr])
        pred[te] = clf.predict(X_te)

    all_f1 = macro_f1(y, pred)
    consistent_mask = strata == "consistent"
    conflict_mask = strata == "conflict"
    all_ci = bootstrap_ci_by_session(y, pred, groups)
    cons_ci = bootstrap_ci_by_session(y, pred, groups, mask=consistent_mask)
    conf_ci = bootstrap_ci_by_session(y, pred, groups, mask=conflict_mask)
    return {
        "setting": "MERCI in-domain (5-fold grouped CV)",
        "macro_f1_all": all_f1,
        "macro_f1_consistent": macro_f1(y[consistent_mask], pred[consistent_mask]) if consistent_mask.any() else None,
        "macro_f1_conflict": macro_f1(y[conflict_mask], pred[conflict_mask]) if conflict_mask.any() else None,
        "ci95_all_low": all_ci[0],
        "ci95_all_high": all_ci[1],
        "ci95_consistent_low": cons_ci[0],
        "ci95_consistent_high": cons_ci[1],
        "ci95_conflict_low": conf_ci[0],
        "ci95_conflict_high": conf_ci[1],
        "n_rows": int(len(rows)),
    }


def load_meld_csv(path: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    vals: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            emo = str(r.get("Emotion", "")).strip().lower()
            txt = str(r.get("Utterance", "")).strip()
            if not txt or emo not in MELD_TO_VALENCE:
                continue
            texts.append(txt)
            vals.append(MELD_TO_VALENCE[emo])
    return texts, vals


def load_iemocap_text_valence(root: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    vals: list[str] = []
    if not root.exists():
        return texts, vals
    for ses in sorted(root.glob("Session*")):
        eval_dir = ses / "dialog" / "EmoEvaluation"
        trs_dir = ses / "dialog" / "transcriptions"
        if not eval_dir.exists() or not trs_dir.exists():
            continue
        for eval_file in sorted(eval_dir.glob("*.txt")):
            utt_to_emo: dict[str, str] = {}
            for line in eval_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"^\[[^\]]+\]\s+(\S+)\s+([a-z]{3})\s+\[", line.strip(), flags=re.I)
                if not m:
                    continue
                utt = m.group(1).strip()
                emo = m.group(2).lower().strip()
                if emo in IEMOCAP_TO_VALENCE:
                    utt_to_emo[utt] = emo
            trs_file = trs_dir / eval_file.name
            if not trs_file.exists():
                continue
            for line in trs_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                m = re.match(r"^(\S+)\s+\[[^\]]+\]:\s*(.*)$", line.strip())
                if not m:
                    continue
                utt = m.group(1).strip()
                txt = m.group(2).strip()
                emo = utt_to_emo.get(utt)
                if not txt or emo is None:
                    continue
                texts.append(txt)
                vals.append(IEMOCAP_TO_VALENCE[emo])
    return texts, vals


def eval_meld_to_merci(rows: list[MerciRow], meld_paths: list[Path]) -> dict:
    train_texts: list[str] = []
    train_vals: list[str] = []
    used_paths: list[str] = []
    for p in meld_paths:
        if not p.exists():
            continue
        t, v = load_meld_csv(p)
        train_texts.extend(t)
        train_vals.extend(v)
        used_paths.append(str(p))

    if not train_texts:
        return {
            "setting": "MELD -> MERCI transfer",
            "status": "missing_meld_files",
            "note": "Provide --meld-train/--meld-dev/--meld-test CSV paths.",
        }

    X_train = train_texts
    y_train = np.array(train_vals, dtype=object)
    X_test = np.array([r.text for r in rows], dtype=object)
    y_test = np.array([r.valence for r in rows], dtype=object)
    groups = np.array([r.session_id for r in rows], dtype=object)
    strata = np.array([r.cross_modal_class for r in rows], dtype=object)

    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=1)
    Xtr = vec.fit_transform(X_train)
    Xte = vec.transform(X_test)
    clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)
    clf.fit(Xtr, y_train)
    pred = clf.predict(Xte)

    consistent_mask = strata == "consistent"
    conflict_mask = strata == "conflict"
    all_ci = bootstrap_ci_by_session(y_test, pred, groups)
    cons_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=consistent_mask)
    conf_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=conflict_mask)
    return {
        "setting": "MELD -> MERCI transfer",
        "status": "ok",
        "meld_files_used": used_paths,
        "meld_train_rows": int(len(y_train)),
        "macro_f1_all": macro_f1(y_test, pred),
        "macro_f1_consistent": macro_f1(y_test[consistent_mask], pred[consistent_mask]) if consistent_mask.any() else None,
        "macro_f1_conflict": macro_f1(y_test[conflict_mask], pred[conflict_mask]) if conflict_mask.any() else None,
        "ci95_all_low": all_ci[0],
        "ci95_all_high": all_ci[1],
        "ci95_consistent_low": cons_ci[0],
        "ci95_consistent_high": cons_ci[1],
        "ci95_conflict_low": conf_ci[0],
        "ci95_conflict_high": conf_ci[1],
        "n_rows": int(len(rows)),
    }


def eval_iemocap_to_merci(rows: list[MerciRow], iemocap_root: Path) -> dict:
    train_texts, train_vals = load_iemocap_text_valence(iemocap_root)
    if not train_texts:
        return {
            "setting": "IEMOCAP -> MERCI transfer",
            "status": "missing_iemocap_files",
            "note": "Provide --iemocap-root with Session1..Session5 directories.",
        }
    X_train = train_texts
    y_train = np.array(train_vals, dtype=object)
    X_test = np.array([r.text for r in rows], dtype=object)
    y_test = np.array([r.valence for r in rows], dtype=object)
    groups = np.array([r.session_id for r in rows], dtype=object)
    strata = np.array([r.cross_modal_class for r in rows], dtype=object)
    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=1)
    Xtr = vec.fit_transform(X_train)
    Xte = vec.transform(X_test)
    clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)
    clf.fit(Xtr, y_train)
    pred = clf.predict(Xte)
    consistent_mask = strata == "consistent"
    conflict_mask = strata == "conflict"
    all_ci = bootstrap_ci_by_session(y_test, pred, groups)
    cons_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=consistent_mask)
    conf_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=conflict_mask)
    return {
        "setting": "IEMOCAP -> MERCI transfer",
        "status": "ok",
        "iemocap_train_rows": int(len(y_train)),
        "macro_f1_all": macro_f1(y_test, pred),
        "macro_f1_consistent": macro_f1(y_test[consistent_mask], pred[consistent_mask]) if consistent_mask.any() else None,
        "macro_f1_conflict": macro_f1(y_test[conflict_mask], pred[conflict_mask]) if conflict_mask.any() else None,
        "ci95_all_low": all_ci[0],
        "ci95_all_high": all_ci[1],
        "ci95_consistent_low": cons_ci[0],
        "ci95_consistent_high": cons_ci[1],
        "ci95_conflict_low": conf_ci[0],
        "ci95_conflict_high": conf_ci[1],
        "n_rows": int(len(rows)),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--meld-train", type=Path, default=OUT_DIR / "meld_train_sent_emo.csv")
    ap.add_argument("--meld-dev", type=Path, default=OUT_DIR / "meld_dev_sent_emo.csv")
    ap.add_argument("--meld-test", type=Path, default=OUT_DIR / "meld_test_sent_emo.csv")
    ap.add_argument(
        "--iemocap-root",
        type=Path,
        default=OUT_DIR / "iemocap_hf" / "data",
        help="Path containing Session1..Session5",
    )
    args = ap.parse_args()

    merci_rows = load_merci_rows()
    res_merci = eval_in_domain_merci(merci_rows)
    res_meld = eval_meld_to_merci(merci_rows, [args.meld_train, args.meld_dev, args.meld_test])
    res_iemocap = eval_iemocap_to_merci(merci_rows, args.iemocap_root)
    rows = [res_merci, res_meld, res_iemocap]

    out_json = OUT_DIR / "benchmark_cross_corpus_merci_meld.json"
    out_csv = OUT_DIR / "benchmark_cross_corpus_merci_meld.csv"
    out_json.write_text(json.dumps({"results": rows}, indent=2), encoding="utf-8")
    write_csv(out_csv, rows)
    print(json.dumps({"results": rows}, indent=2))


if __name__ == "__main__":
    main()
