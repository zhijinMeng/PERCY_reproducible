#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profile persona prompts + topic rotation (MERCI gpt4_server style)."""
from __future__ import print_function

import json
import os


DEFAULT_PERSONA_GREETING = (
    "Hello, I am PERCY, the Personal Emotional Robotic Conversation system. "
    "I am here to have a natural conversation with you based on your profile. "
    "Let's have a great conversation!"
)

TOPIC_WRAP_UP_NOTE = (
    "TOPIC WRAP-UP (this turn only): React to the user's last message with "
    "exactly ONE short empathic sentence. You MUST NOT ask any question. "
    "Do not use a question mark. Do not invite further discussion on this topic."
)

TOPIC_INTRO_NOTE = (
    "NEW TOPIC (this turn only): The previous topic is finished. "
    "Say one brief transition (e.g. 'Let's talk about something else.'), "
    "then ask exactly ONE question about the NEW profile topic below. "
    "Do not mention or ask about the previous topic. "
    "Question: {question}  Participant's survey answer: {answer}"
)

TOPIC_CHANGE_TEMPLATE = (
    "Profile topic for the next question: "
    "Question: {question}  Answer: {answer}"
)


def profile_path(session_dir):
    return os.path.join(session_dir, "profile.json")


def load_profile(session_dir):
    path = profile_path(session_dir)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        return None
    return data


def profile_summary(profile):
    lines = []
    for pair in profile:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        q = pair[0].get("content", "")
        a = pair[1].get("content", "")
        if q and a:
            lines.append("- Q: %s  A: %s" % (q, a))
    return "\n".join(lines)


def build_persona_system_content(profile):
    """Persona rubric: shorter than legacy gpt4_server, keeps MERCI intent."""
    summary = profile_summary(profile)
    return (
        "Your name is PERCY (Personal Emotional Robotic Conversation sYstem). "
        "You are empathic, friendly, and professional. "
        "Engage in natural spoken dialogue based on the participant profile below. "
        "Ask deeper follow-up questions about their interests and experiences. "
        "Use simple vocabulary; avoid academic wording and yes/no questions when possible. "
        "Ask one question at a time and wait for the user to respond. "
        "Show empathy by acknowledging the user's feelings when emotion cues are provided. "
        "Stay consistent with the profile and prior turns. "
        "Keep replies short for speech: one or two sentences.\n\n"
        "Participant profile (pre-session questionnaire):\n"
        "%s"
    ) % summary


class ProfileTopicManager(object):
    """Rotate through profile Q&A pairs every N user turns (legacy: 3)."""

    def __init__(self, profile, followups_per_topic=3):
        self.profile = profile or []
        self.followups_per_topic = int(followups_per_topic)
        self.current_index = 0
        self.printed_pairs = set()
        self.topic_counter = 0
        self.exhausted = False

    def change_topic(self):
        if self.exhausted or self.current_index >= len(self.profile):
            self.exhausted = True
            return None, None

        pair = self.profile[self.current_index]
        question = pair[0].get("content", "")
        answer = pair[1].get("content", "")
        key = (question, answer)
        if not question or not answer or key in self.printed_pairs:
            self.current_index += 1
            return self.change_topic()

        self.printed_pairs.add(key)
        self.current_index += 1
        return (
            {"role": "assistant", "content": question},
            {"role": "user", "content": answer},
        )

    def seed_first_topic(self, messages):
        question, answer = self.change_topic()
        if not question:
            return messages
        out = list(messages)
        out.append(question)
        out.append(answer)
        return out

    def on_user_turn(self):
        self.topic_counter += 1
        return self.topic_counter

    def should_wrap_up_topic(self):
        return self.topic_counter == self.followups_per_topic

    def should_change_topic(self):
        return self.topic_counter >= self.followups_per_topic

    def reset_topic_counter(self):
        self.topic_counter = 0

    def build_topic_intro_note(self, question, answer):
        q_text = question.get("content", "")
        a_text = answer.get("content", "")
        return TOPIC_INTRO_NOTE.format(question=q_text, answer=a_text)

    def build_topic_change_messages(self, question, answer):
        q_text = question.get("content", "")
        a_text = answer.get("content", "")
        return [
            {
                "role": "system",
                "content": TOPIC_CHANGE_TEMPLATE.format(question=q_text, answer=a_text),
            },
            question,
            answer,
        ]

    @property
    def topics_remaining(self):
        return max(0, len(self.profile) - self.current_index)


def sanitize_wrap_up_reply(text):
    """Drop trailing questions if the model still asks one on wrap-up turn."""
    text = (text or "").strip()
    if not text:
        return text
    if "?" in text:
        parts = text.split("?")
        text = parts[0].strip()
        if text and not text.endswith((".", "!")):
            text += "."
    return text
