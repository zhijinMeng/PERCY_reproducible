#!/usr/bin/env python3
"""Cross-corpus benchmark with frozen DistilRoBERTa embeddings + linear head."""
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold
from transformers import AutoModel, AutoTokenizer

from merci_message_io import EMOTIONS
from merci_normalized_media import iter_normalized_sessions, load_session_messages

OUT_DIR = Path(__file__).parent
N_FOLDS = 5
BOOT_B = 2000
BOOT_SEED = 42
VALENCE_ORDER = ["negative", "neutral", "positive"]
VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}
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
            txt = str(msg.get("content") or "").strip()
            if em not in EMOTIONS or sn not in {"positive", "neutral", "negative"} or not txt:
                continue
            rows.append(MerciRow(sid, txt, sn, classify_valence_conflict(em, sn)))
    return rows


def load_meld_csv(path: Path) -> tuple[list[str], list[str]]:
    texts, vals = [], []
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


def load_encoder(model_name: str):
    tok = AutoTokenizer.from_pretrained(model_name, local_files_only=True)
    model = AutoModel.from_pretrained(model_name, local_files_only=True)
    model.to(torch.device("cpu"))
    model.eval()
    return tok, model


def embed_texts(
    texts: list[str],
    tok,
    model,
    batch_size: int = 32,
    max_len: int = 128,
) -> np.ndarray:
    device = torch.device("cpu")
    all_vecs = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            enc = tok(batch, padding=True, truncation=True, max_length=max_len, return_tensors="pt")
            enc = {k: v.to(device) for k, v in enc.items()}
            out = model(**enc).last_hidden_state
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (out * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1.0)
            all_vecs.append(pooled.cpu().numpy())
    return np.vstack(all_vecs)


def eval_merci_cv(rows: list[MerciRow], feats: np.ndarray) -> dict:
    y = np.array([r.valence for r in rows], dtype=object)
    groups = np.array([r.session_id for r in rows], dtype=object)
    strata = np.array([r.cross_modal_class for r in rows], dtype=object)
    pred = np.empty(len(rows), dtype=object)
    gkf = GroupKFold(n_splits=N_FOLDS)
    for tr, te in gkf.split(feats, y, groups=groups):
        clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)
        clf.fit(feats[tr], y[tr])
        pred[te] = clf.predict(feats[te])
    cons = strata == "consistent"
    conf = strata == "conflict"
    all_ci = bootstrap_ci_by_session(y, pred, groups)
    cons_ci = bootstrap_ci_by_session(y, pred, groups, mask=cons)
    conf_ci = bootstrap_ci_by_session(y, pred, groups, mask=conf)
    return {
        "setting": "MERCI in-domain (5-fold grouped CV)",
        "model": "Frozen DistilRoBERTa + linear head",
        "macro_f1_all": macro_f1(y, pred),
        "macro_f1_consistent": macro_f1(y[cons], pred[cons]) if cons.any() else None,
        "macro_f1_conflict": macro_f1(y[conf], pred[conf]) if conf.any() else None,
        "ci95_all_low": all_ci[0],
        "ci95_all_high": all_ci[1],
        "ci95_consistent_low": cons_ci[0],
        "ci95_consistent_high": cons_ci[1],
        "ci95_conflict_low": conf_ci[0],
        "ci95_conflict_high": conf_ci[1],
        "n_rows": int(len(rows)),
    }


def eval_meld_transfer(rows: list[MerciRow], merci_feats: np.ndarray, meld_texts: list[str], meld_vals: list[str], tok, model) -> dict:
    if not meld_texts:
        return {"setting": "MELD -> MERCI transfer", "status": "missing_meld_files"}
    meld_feats = embed_texts(meld_texts, tok=tok, model=model)
    y_train = np.array(meld_vals, dtype=object)
    y_test = np.array([r.valence for r in rows], dtype=object)
    groups = np.array([r.session_id for r in rows], dtype=object)
    strata = np.array([r.cross_modal_class for r in rows], dtype=object)
    clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)
    clf.fit(meld_feats, y_train)
    pred = clf.predict(merci_feats)
    cons = strata == "consistent"
    conf = strata == "conflict"
    all_ci = bootstrap_ci_by_session(y_test, pred, groups)
    cons_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=cons)
    conf_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=conf)
    return {
        "setting": "MELD -> MERCI transfer",
        "model": "Frozen DistilRoBERTa + linear head",
        "status": "ok",
        "meld_train_rows": int(len(y_train)),
        "macro_f1_all": macro_f1(y_test, pred),
        "macro_f1_consistent": macro_f1(y_test[cons], pred[cons]) if cons.any() else None,
        "macro_f1_conflict": macro_f1(y_test[conf], pred[conf]) if conf.any() else None,
        "ci95_all_low": all_ci[0],
        "ci95_all_high": all_ci[1],
        "ci95_consistent_low": cons_ci[0],
        "ci95_consistent_high": cons_ci[1],
        "ci95_conflict_low": conf_ci[0],
        "ci95_conflict_high": conf_ci[1],
        "n_rows": int(len(rows)),
    }


def eval_iemocap_transfer(rows: list[MerciRow], merci_feats: np.ndarray, iemocap_texts: list[str], iemocap_vals: list[str], tok, model) -> dict:
    if not iemocap_texts:
        return {"setting": "IEMOCAP -> MERCI transfer", "status": "missing_iemocap_files"}
    iemocap_feats = embed_texts(iemocap_texts, tok=tok, model=model)
    y_train = np.array(iemocap_vals, dtype=object)
    y_test = np.array([r.valence for r in rows], dtype=object)
    groups = np.array([r.session_id for r in rows], dtype=object)
    strata = np.array([r.cross_modal_class for r in rows], dtype=object)
    clf = LogisticRegression(max_iter=3000, class_weight="balanced", random_state=42)
    clf.fit(iemocap_feats, y_train)
    pred = clf.predict(merci_feats)
    cons = strata == "consistent"
    conf = strata == "conflict"
    all_ci = bootstrap_ci_by_session(y_test, pred, groups)
    cons_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=cons)
    conf_ci = bootstrap_ci_by_session(y_test, pred, groups, mask=conf)
    return {
        "setting": "IEMOCAP -> MERCI transfer",
        "model": "Frozen DistilRoBERTa + linear head",
        "status": "ok",
        "iemocap_train_rows": int(len(y_train)),
        "macro_f1_all": macro_f1(y_test, pred),
        "macro_f1_consistent": macro_f1(y_test[cons], pred[cons]) if cons.any() else None,
        "macro_f1_conflict": macro_f1(y_test[conf], pred[conf]) if conf.any() else None,
        "ci95_all_low": all_ci[0],
        "ci95_all_high": all_ci[1],
        "ci95_consistent_low": cons_ci[0],
        "ci95_consistent_high": cons_ci[1],
        "ci95_conflict_low": conf_ci[0],
        "ci95_conflict_high": conf_ci[1],
        "n_rows": int(len(rows)),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-name", default="distilroberta-base")
    ap.add_argument("--meld-train", type=Path, default=OUT_DIR / "meld_train_sent_emo.csv")
    ap.add_argument("--meld-dev", type=Path, default=OUT_DIR / "meld_dev_sent_emo.csv")
    ap.add_argument("--meld-test", type=Path, default=OUT_DIR / "meld_test_sent_emo.csv")
    ap.add_argument("--iemocap-root", type=Path, default=OUT_DIR / "iemocap_hf" / "data")
    args = ap.parse_args()

    rows = load_merci_rows()
    merci_texts = [r.text for r in rows]
    tok, model = load_encoder(args.model_name)
    merci_feats = embed_texts(merci_texts, tok=tok, model=model)

    meld_texts, meld_vals = [], []
    for p in [args.meld_train, args.meld_dev, args.meld_test]:
        if p.exists():
            t, v = load_meld_csv(p)
            meld_texts.extend(t)
            meld_vals.extend(v)
    iemocap_texts, iemocap_vals = load_iemocap_text_valence(args.iemocap_root)

    res_merci = eval_merci_cv(rows, merci_feats)
    res_meld = eval_meld_transfer(rows, merci_feats, meld_texts, meld_vals, tok=tok, model=model)
    res_iemocap = eval_iemocap_transfer(
        rows, merci_feats, iemocap_texts, iemocap_vals, tok=tok, model=model
    )
    results = [res_merci, res_meld, res_iemocap]

    out_json = OUT_DIR / "benchmark_cross_corpus_merci_meld_roberta.json"
    out_csv = OUT_DIR / "benchmark_cross_corpus_merci_meld_roberta.csv"
    out_json.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")
    write_csv(out_csv, results)
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
