# -*- coding: utf-8 -*-
"""Build gpt4_server-compatible profile.json from pre-session survey answers."""
from __future__ import print_function

import json
import os
from datetime import datetime, timezone


def _schema_path(name):
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "schemas", "%s.json" % name)


def load_schema(survey_id):
    path = _schema_path(survey_id)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_questions(schema):
    for section in schema.get("sections", []):
        for q in section.get("questions", []):
            yield q


def _answer_text(question, answers):
    qid = question["id"]
    raw = answers.get(qid)
    if raw is None or raw == "" or raw == []:
        return None

    qtype = question.get("type")
    if qtype == "checkbox":
        return "yes" if raw else None
    if qtype == "multiselect":
        if not isinstance(raw, list):
            raw = [raw]
        parts = [str(x) for x in raw if x and x != "Other"]
        other_id = question.get("other_id")
        if other_id and "Other" in raw:
            other_val = (answers.get(other_id) or "").strip()
            if other_val:
                parts.append(other_val)
        return ", ".join(parts) if parts else None
    if qtype == "select":
        if raw == "Other":
            other_id = question.get("other_id")
            other_val = (answers.get(other_id) or "").strip() if other_id else ""
            return other_val or "Other"
        return str(raw)
    return str(raw).strip() or None


def build_profile_pairs(schema, answers):
    pairs = []
    for q in iter_questions(schema):
        if not q.get("profile_topic"):
            continue
        text = _answer_text(q, answers)
        if not text:
            continue
        label = q.get("prompt_label") or q.get("label") or q["id"]
        pairs.append(
            [
                {"role": "system", "content": label},
                {"role": "user", "content": text},
            ]
        )
    return pairs


def build_participant_meta(schema, answers):
    meta = {}
    for q in iter_questions(schema):
        if not q.get("meta"):
            continue
        text = _answer_text(q, answers)
        if text is not None:
            meta[q["id"]] = text
    return meta


def save_pre_session(session_dir, schema, answers, session_id=None):
    os.makedirs(session_dir, exist_ok=True)
    submitted_at = datetime.now(timezone.utc).isoformat()
    meta = build_participant_meta(schema, answers)
    profile_pairs = build_profile_pairs(schema, answers)

    pre_doc = {
        "survey_id": schema.get("id", "pre_session"),
        "qualtrics_ref": schema.get("qualtrics_ref"),
        "session_id": session_id or os.path.basename(session_dir.rstrip(os.sep)),
        "submitted_at": submitted_at,
        "answers": answers,
        "participant_meta": meta,
        "profile_topic_count": len(profile_pairs),
    }
    pre_path = os.path.join(session_dir, "pre_survey.json")
    with open(pre_path, "w", encoding="utf-8") as f:
        json.dump(pre_doc, f, indent=2, ensure_ascii=False)

    profile_path = os.path.join(session_dir, "profile.json")
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile_pairs, f, indent=2, ensure_ascii=False)

    return pre_path, profile_path, profile_pairs


def save_post_session(session_dir, schema, answers, session_id=None):
    os.makedirs(session_dir, exist_ok=True)
    post_doc = {
        "survey_id": schema.get("id", "post_session"),
        "qualtrics_ref": schema.get("qualtrics_ref"),
        "session_id": session_id or os.path.basename(session_dir.rstrip(os.sep)),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
    }
    post_path = os.path.join(session_dir, "post_survey.json")
    with open(post_path, "w", encoding="utf-8") as f:
        json.dump(post_doc, f, indent=2, ensure_ascii=False)
    return post_path
