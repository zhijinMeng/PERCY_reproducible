#!/usr/bin/env python3
"""Benchmark C: affect-conditioned turn retrieval on MERCI.

Protocol:
- Query spec is externalized in benchmark_c_queries.json
- Text-only ranker: TF-IDF cosine
- Metadata ranker: exact match over released fields
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from merci_message_io import EMOTIONS
from merci_normalized_media import iter_normalized_sessions, load_session_messages

OUT_DIR = Path(__file__).parent

VISUAL_NEGATIVE = {"sad", "angry", "disgust", "fear"}


@dataclass
class Turn:
    session_id: str
    text: str
    emotion: str
    sentiment: str
    cls: str


@dataclass
class Query:
    qid: str
    text: str
    kind: str
    filters: dict[str, str] | None = None


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


def load_turns() -> list[Turn]:
    audited_csv = OUT_DIR / "cross_modal_per_session.csv"
    audited_sessions: set[str] | None = None
    if audited_csv.exists():
        with audited_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            audited_sessions = {str(r.get("session_id", "")).strip() for r in reader if r.get("session_id")}

    rows: list[Turn] = []
    for sid, session_dir in iter_normalized_sessions():
        if audited_sessions is not None and sid not in audited_sessions:
            continue
        messages = load_session_messages(session_dir)
        for msg in messages:
            if msg.get("role") != "user":
                continue
            em = str(msg.get("emotion_visual") or msg.get("emotion") or "").lower().strip()
            sn = str(msg.get("sentiment") or "").lower().strip()
            txt = str(msg.get("content") or "").strip()
            if em not in EMOTIONS or sn not in {"positive", "neutral", "negative"} or not txt:
                continue
            rows.append(Turn(sid, txt, em, sn, classify_valence_conflict(em, sn)))
    return rows


def load_queries() -> list[Query]:
    q_path = OUT_DIR / "benchmark_c_queries.json"
    data = json.loads(q_path.read_text(encoding="utf-8"))
    out: list[Query] = []
    for item in data:
        out.append(
            Query(
                qid=str(item["qid"]),
                text=str(item["text"]),
                kind=str(item["kind"]),
                filters=dict(item.get("filters", {})),
            )
        )
    return out


def relevance(turns: list[Turn], q: Query) -> np.ndarray:
    rel = np.ones(len(turns), dtype=bool)
    filt = q.filters or {}
    if "cross_modal_class" in filt:
        rel &= np.array([t.cls == filt["cross_modal_class"] for t in turns])
    if "emotion" in filt:
        rel &= np.array([t.emotion == filt["emotion"] for t in turns])
    if "sentiment" in filt:
        rel &= np.array([t.sentiment == filt["sentiment"] for t in turns])
    return rel.astype(int)


def ndcg_at_k(rel: np.ndarray, ranked_idx: np.ndarray, k: int = 10) -> float:
    gains = rel[ranked_idx[:k]]
    if gains.sum() == 0:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, 2 + len(gains)))
    dcg = float((gains * discounts).sum())
    ideal = np.sort(rel)[::-1][:k]
    idcg = float((ideal * discounts[: len(ideal)]).sum())
    return dcg / idcg if idcg > 0 else 0.0


def recall_at_k(rel: np.ndarray, ranked_idx: np.ndarray, k: int = 10) -> float:
    denom = int(rel.sum())
    if denom == 0:
        return 0.0
    return float(rel[ranked_idx[:k]].sum() / denom)


def rank_text_only(turns: list[Turn], queries: list[Query]) -> list[np.ndarray]:
    docs = [t.text for t in turns]
    qtxt = [q.text for q in queries]
    vec = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=1)
    X = vec.fit_transform(docs)
    Q = vec.transform(qtxt)
    sims = (Q @ X.T).toarray()
    return [np.argsort(-sims[i]) for i in range(len(queries))]


def rank_metadata_exact(turns: list[Turn], queries: list[Query]) -> list[np.ndarray]:
    """Rank all exact-matched turns first; unmatched turns stay after."""
    out = []
    n = len(turns)
    for q in queries:
        exact = np.zeros(n, dtype=float)
        filt = q.filters or {}
        if "cross_modal_class" in filt:
            exact += np.array([1.0 if t.cls == filt["cross_modal_class"] else 0.0 for t in turns])
        if "emotion" in filt:
            exact += np.array([1.0 if t.emotion == filt["emotion"] else 0.0 for t in turns])
        if "sentiment" in filt:
            exact += np.array([1.0 if t.sentiment == filt["sentiment"] else 0.0 for t in turns])
        needed = max(1, len(filt))
        matched = exact >= float(needed)
        # Stable ordering keeps original index order inside matched/unmatched sets.
        rank_score = np.where(matched, 1.0, 0.0)
        out.append(np.argsort(-rank_score, kind="mergesort"))
    return out


def main() -> None:
    turns = load_turns()
    queries = load_queries()
    text_ranks = rank_text_only(turns, queries)
    metadata_ranks = rank_metadata_exact(turns, queries)

    rows = []
    for q, r_text, r_meta in zip(queries, text_ranks, metadata_ranks):
        rel = relevance(turns, q)
        rows.append(
            {
                "query_id": q.qid,
                "query_kind": q.kind,
                "query_text": q.text,
                "relevant_n": int(rel.sum()),
                "text_recall@10": recall_at_k(rel, r_text, 10),
                "text_ndcg@10": ndcg_at_k(rel, r_text, 10),
                "metadata_recall@10": recall_at_k(rel, r_meta, 10),
                "metadata_ndcg@10": ndcg_at_k(rel, r_meta, 10),
            }
        )

    by_kind = {}
    for kind in sorted(set(r["query_kind"] for r in rows)):
        sub = [r for r in rows if r["query_kind"] == kind]
        by_kind[kind] = {
            "n_queries": len(sub),
            "text_recall@10": float(np.mean([r["text_recall@10"] for r in sub])),
            "text_ndcg@10": float(np.mean([r["text_ndcg@10"] for r in sub])),
            "metadata_recall@10": float(np.mean([r["metadata_recall@10"] for r in sub])),
            "metadata_ndcg@10": float(np.mean([r["metadata_ndcg@10"] for r in sub])),
        }

    summary = {
        "n_turns": len(turns),
        "n_queries": len(queries),
        "query_spec_file": str((OUT_DIR / "benchmark_c_queries.json").name),
        "metadata_exact_match": {
            "rule": "all query filters must match exactly",
            "filter_fields": ["cross_modal_class", "emotion", "sentiment"],
        },
        "query_summary_by_kind": by_kind,
    }

    out_csv = OUT_DIR / "benchmark_c_affect_retrieval.csv"
    out_json = OUT_DIR / "benchmark_c_affect_retrieval_summary.json"
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
