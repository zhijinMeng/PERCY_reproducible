#!/usr/bin/env python3
"""
Real-time turn-taking dialogue for PERCY benchmark.

  USB mic (/audio/rode) + robot TTS; optional stamp-aligned A/V in parallel.

Design:
  - End-of-utterance: Silero VAD (default) or legacy WebRTC VAD
  - Timeline t=0 from latched /percy/session/t0 (recorder wall clock)
  - Optional: rosservice call /percy_live/end_turn to cut early

Outputs (PERCY_DATA_DIR/<session_id>/):
  chat_history.json, dialogue_timeline.json, utterances/user_*.wav, session_events.jsonl
"""
from __future__ import print_function

import enum
import json
import os
import struct
import sys
import threading
import time
import wave

import rospy
import webrtcvad
from actionlib import GoalStatus, SimpleActionClient
from audio_common_msgs.msg import AudioData
from openai import OpenAI
from pal_interaction_msgs.msg import TtsAction, TtsGoal, TtsFeedback
from std_msgs.msg import Float64
from std_srvs.srv import Trigger, TriggerResponse

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from session_timeline import (
    default_data_root,
    session_dir,
    utterances_dir,
    user_utterance_wav_path,
)
from vad_noise_gate import (
    calibrate_rms_threshold_from_wav,
    is_active_speech_frame,
    resolve_auto_noise_profile,
)

_AFFECT_CHAT_KEYS = (
    "emotion_visual",
    "sentiment",
    "sentiment_score",
    "affect_fused",
    "affect_fused_confidence",
    "affect_fusion_weights",
    "affect_fused_distribution",
    "cross_modal_valence_conflict",
)


class State(enum.Enum):
    LISTEN = "listen"
    PROCESS = "process"
    SPEAK = "speak"
    COOLDOWN = "cooldown"


# Whisper 在 <2.5s 风扇/底噪切片上常见幻听（与是否真说话无关）
_SHORT_WHISPER_HALLUCINATIONS = frozenset(
    {
        "seriously",
        "that's your mission",
        "this is your mission",
        "thank you",
        "thanks for watching",
        "subscribe",
        "you",
        "bye",
        "goodbye",
        "okay",
        "ok",
        "yeah",
        "yes",
        "no",
        "hmm",
        "um",
        "uh",
        "change",
        "the end",
        "music",
        "applause",
    }
)


class LiveDialogue(object):
    FRAME_MS = 30

    def __init__(self):
        rospy.init_node("live_dialogue")

        self._session_id = str(rospy.get_param("~session_id", "0"))
        self._audio_topic = rospy.get_param("~audio_topic", "/audio/rode")
        self._sample_rate = int(rospy.get_param("~sample_rate", 16000))
        self._vad_backend = str(rospy.get_param("~vad_backend", "silero")).strip().lower()
        self._vad_mode = int(rospy.get_param("~vad_mode", 3))
        self._audio_gain = float(rospy.get_param("~audio_gain", 2.0))
        self._silero_threshold = float(rospy.get_param("~silero_threshold", 0.5))
        self._silero_speech_pad_ms = int(rospy.get_param("~silero_speech_pad_ms", 100))
        self._enable_noise_gate = bool(rospy.get_param("~enable_noise_gate", False))
        self._noise_gate_rms = int(rospy.get_param("~noise_gate_rms", 0))
        self._noise_gate_profile = str(
            rospy.get_param("~noise_gate_profile_wav", "__auto__")
        ).strip()
        self._noise_gate_capture_gain = float(
            rospy.get_param("~noise_gate_capture_gain", 2.5)
        )
        self._noise_gate_margin = float(rospy.get_param("~noise_gate_margin", 1.35))
        self._noise_gate_hangover = float(
            rospy.get_param("~noise_gate_hangover_ratio", 1.0)
        )
        self._noise_gate_start_ratio = float(
            rospy.get_param("~noise_gate_start_ratio", 0.65)
        )
        self._noise_gate_min_active_frames = int(
            rospy.get_param("~noise_gate_min_active_frames", 3)
        )
        self._end_silence = float(rospy.get_param("~end_silence_sec", 0.8))
        self._min_speech = float(rospy.get_param("~min_speech_sec", 0.8))
        self._min_whisper_sec = float(rospy.get_param("~min_whisper_sec", 1.2))
        self._noise_gate_only_at_start = bool(
            rospy.get_param("~noise_gate_only_at_start", True)
        )
        self._noise_gate_start_frames = int(
            rospy.get_param("~noise_gate_start_frames", 4)
        )
        self._reject_short_hallucinations = bool(
            rospy.get_param("~reject_short_hallucinations", True)
        )
        self._short_hallucination_max_sec = float(
            rospy.get_param("~short_hallucination_max_sec", 2.5)
        )
        self._max_utterance = float(rospy.get_param("~max_utterance_sec", 25.0))
        self._api_retries = int(rospy.get_param("~openai_retries", 3))
        self._post_tts_mute = float(rospy.get_param("~post_tts_mute_sec", 0.6))
        self._whisper_model = str(rospy.get_param("~whisper_model", "whisper-1"))
        self._chat_model = str(rospy.get_param("~chat_model", "gpt-4o-mini"))
        self._enable_affect = bool(rospy.get_param("~enable_affect", True))
        self._enable_visual_affect = bool(rospy.get_param("~enable_visual_affect", True))
        self._enable_affect_prompt = bool(rospy.get_param("~enable_affect_prompt", True))
        # True（默认）：情感只后台写入 JSON，不挡 GPT/TTS；视觉 FER 仅为缓存快照
        self._affect_async = bool(rospy.get_param("~affect_async", True))
        self._visual_emotion_topic = str(
            rospy.get_param("~visual_emotion_topic", "emotiondetect_result")
        ).strip()
        self._face_detections_topic = str(
            rospy.get_param("~face_detections_topic", "")
        ).strip()
        self._affect_w_visual = float(rospy.get_param("~affect_w_visual", 0.6))
        self._affect_w_text = float(rospy.get_param("~affect_w_text", 0.4))
        self._play_greeting = bool(rospy.get_param("~play_greeting", True))
        self._enable_profile = bool(rospy.get_param("~enable_profile", True))
        self._profile_followups = int(rospy.get_param("~profile_followups_per_topic", 3))
        self._greeting = str(
            rospy.get_param(
                "~greeting_text",
                "Hello! I am PERCY. Say something, and I will reply.",
            )
        )
        self._t0_timeout = float(rospy.get_param("~session_t0_timeout_sec", 60.0))
        self._t0_topic = str(rospy.get_param("~session_t0_topic", "/percy/session/t0"))

        data_root = rospy.get_param("~data_root", "__auto__")
        if not data_root or data_root == "__auto__":
            data_root = default_data_root()
        self._out_dir = session_dir(data_root, self._session_id)
        os.makedirs(self._out_dir, exist_ok=True)
        self._utterances_subdir = str(
            rospy.get_param("~utterances_subdir", "utterances")
        ).strip() or "utterances"
        self._utterances_dir = utterances_dir(self._out_dir, self._utterances_subdir)
        self._history_path = os.path.join(self._out_dir, "chat_history.json")
        self._timeline_path = os.path.join(self._out_dir, "dialogue_timeline.json")
        self._events_path = os.path.join(self._out_dir, "session_events.jsonl")

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            rospy.logfatal("OPENAI_API_KEY not set")
            sys.exit(1)
        self._openai = OpenAI(api_key=api_key)

        self._silero_stream = None
        self._vad = None
        self._frame_bytes = int(self._sample_rate * self.FRAME_MS / 1000) * 2
        self._noise_gate_threshold = 0
        if self._vad_backend == "silero":
            rospy.loginfo("Loading Silero VAD model (first run may download weights) …")
            from silero_vad_stream import SileroVadStream

            self._silero_stream = SileroVadStream(
                sample_rate=self._sample_rate,
                threshold=self._silero_threshold,
                min_silence_duration_ms=int(self._end_silence * 1000),
                speech_pad_ms=self._silero_speech_pad_ms,
            )
            rospy.loginfo(
                "VAD backend=silero threshold=%.2f min_silence_ms=%d pad_ms=%d",
                self._silero_threshold,
                int(self._end_silence * 1000),
                self._silero_speech_pad_ms,
            )
        elif self._vad_backend == "webrtc":
            self._vad = webrtcvad.Vad(self._vad_mode)
            self._noise_gate_threshold = self._init_noise_gate_threshold(data_root)
            rospy.loginfo(
                "VAD backend=webrtc mode=%d noise_gate=%s",
                self._vad_mode,
                self._enable_noise_gate,
            )
        else:
            rospy.logfatal("Unknown vad_backend=%s (use silero or webrtc)", self._vad_backend)
            sys.exit(1)

        self._lock = threading.Lock()
        self._state = State.LISTEN
        self._pcm_pending = bytearray()
        self._utterance_pcm = bytearray()
        self._speech_started = False
        self._speech_start_ros = None
        self._last_speech_ros = None
        self._active_streak = 0
        self._pending_start_frames = 0
        self._last_listen_hint_ros = 0.0
        self._cooldown_until = 0.0
        self._listen_enabled = False
        self._turn_idx = 0
        self._timeline_turns = []

        self._t0_ros = None
        self._t0_source = None

        self._profile = None
        self._topic_manager = None
        self._messages = [
            {
                "role": "system",
                "content": (
                    "You are PERCY, a friendly social robot. "
                    "Short spoken replies: one or two sentences, simple English."
                ),
            }
        ]
        if self._enable_profile:
            from percy_profile import (
                DEFAULT_PERSONA_GREETING,
                ProfileTopicManager,
                build_persona_system_content,
                load_profile,
            )

            self._profile = load_profile(self._out_dir)
            if self._profile:
                self._messages[0]["content"] = build_persona_system_content(
                    self._profile
                )
                if self._greeting == "Hello! I am PERCY. Say something, and I will reply.":
                    self._greeting = DEFAULT_PERSONA_GREETING
                self._topic_manager = ProfileTopicManager(
                    self._profile,
                    followups_per_topic=self._profile_followups,
                )
                self._messages = self._topic_manager.seed_first_topic(self._messages)
        self._load_history()

        self._vader = None
        self._visual_tracker = None
        if self._enable_affect:
            from percy_affect import VisualEmotionTracker, load_vader_analyzer

            self._vader = load_vader_analyzer()
            if self._enable_visual_affect:
                self._visual_tracker = VisualEmotionTracker(
                    string_topic=self._visual_emotion_topic or "",
                    face_topic=self._face_detections_topic,
                )

        self._tts = SimpleActionClient("/tts", TtsAction)
        rospy.loginfo("Waiting for /tts ...")
        self._tts.wait_for_server()
        rospy.Subscriber("/tts/feedback", TtsFeedback, self._tts_feedback, queue_size=20)
        rospy.Subscriber(
            self._t0_topic, Float64, self._on_session_t0, queue_size=1
        )
        rospy.Subscriber(
            self._audio_topic, AudioData, self._audio_cb, queue_size=200, buff_size=2**20
        )
        rospy.Service("/percy_live/end_turn", Trigger, self._srv_end_turn)

        self._wait_session_t0()
        rospy.loginfo(
            "live_dialogue: session=%s audio=%s t0=%.3f (%s) vad_backend=%s "
            "gain=%.1f end_silence=%.2fs max_utt=%.1fs affect=%s visual=%s "
            "prompt=%s async=%s profile=%s loaded=%s out=%s",
            self._session_id,
            self._audio_topic,
            self._t0_ros or -1,
            self._t0_source,
            self._vad_backend,
            self._audio_gain,
            self._end_silence,
            self._max_utterance,
            self._enable_affect,
            self._enable_visual_affect,
            self._enable_affect_prompt,
            self._affect_async,
            self._enable_profile,
            bool(self._profile),
            self._out_dir,
        )
        if self._enable_profile and self._profile:
            rospy.loginfo(
                "Profile: loaded %d topics from profile.json (rotate every %d user turns)",
                len(self._profile),
                self._profile_followups,
            )
        elif self._enable_profile:
            rospy.logwarn(
                "Profile: no profile.json in %s (run pre-session survey first)",
                self._out_dir,
            )
        if self._enable_affect:
            rospy.loginfo(
                "Affect: async=%s (does not block TTS); affect_prompt=%s",
                self._affect_async,
                self._enable_affect_prompt,
            )
        self._log_event("node_ready")

        if self._play_greeting:
            with self._lock:
                self._state = State.SPEAK
            greeting_text = self._greeting
            if self._topic_manager is not None:
                try:
                    opening = self._call_openai(
                        "GPT opening",
                        lambda: self._chat(),
                    )
                    if opening:
                        greeting_text = (self._greeting + " " + opening).strip()
                except Exception as e:
                    rospy.logwarn("Profile opening GPT failed: %s", e)
            self._speak(greeting_text, is_greeting=True)
        else:
            self._listen_enabled = True
            rospy.loginfo("Ready — speak (no greeting)")

        rospy.on_shutdown(self._on_shutdown)

    def _wait_session_t0(self):
        deadline = time.time() + self._t0_timeout
        while self._t0_ros is None and time.time() < deadline and not rospy.is_shutdown():
            rospy.sleep(0.05)
        if self._t0_ros is None:
            self._t0_ros = rospy.Time.now().to_sec()
            self._t0_source = "dialogue_fallback_ros_now"
            rospy.logwarn(
                "No %s within %.0fs; fallback t0=%.3f",
                self._t0_topic,
                self._t0_timeout,
                self._t0_ros,
            )
        self._write_timeline_doc()

    def _on_session_t0(self, msg):
        if self._t0_ros is not None:
            return
        self._t0_ros = float(msg.data)
        self._t0_source = "ros_topic:%s" % self._t0_topic
        self._write_timeline_doc()
        rospy.loginfo("Session t0 from %s: %.3f", self._t0_topic, self._t0_ros)

    @staticmethod
    def _now_ros():
        return rospy.Time.now().to_sec()

    def _t_sec(self, ros_sec=None):
        if self._t0_ros is None or ros_sec is None:
            return None
        return round(float(ros_sec) - self._t0_ros, 4)

    def _log_event(self, typ, **extra):
        row = {
            "t_sec": self._t_sec(self._now_ros()),
            "ros_sec": self._now_ros(),
            "type": typ,
        }
        row.update(extra)
        try:
            with open(self._events_path, "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            rospy.logwarn("session_events: %s", e)

    def _write_timeline_doc(self):
        doc = {
            "session_id": self._session_id,
            "timeline_origin_ros_sec": self._t0_ros,
            "timeline_origin_source": self._t0_source,
            "note": "t_start_sec relative to session t0 (wall ROS time at recording start).",
            "turns": list(self._timeline_turns),
        }
        with open(self._timeline_path, "w") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)

    def _commit_turn(self, role, content, t_start_ros, t_end_ros, extra=None):
        row = {
            "turn": self._turn_idx,
            "role": role,
            "content": content,
            "t_start_sec": self._t_sec(t_start_ros),
            "t_end_sec": self._t_sec(t_end_ros),
            "t_start_ros": t_start_ros,
            "t_end_ros": t_end_ros,
        }
        if extra:
            row.update(extra)
        self._timeline_turns.append(row)
        self._write_timeline_doc()
        chat_row = {
            "turn": row["turn"],
            "role": role,
            "content": content,
            "t_start_sec": row["t_start_sec"],
            "t_end_sec": row["t_end_sec"],
        }
        if extra:
            for key in _AFFECT_CHAT_KEYS:
                if key in extra:
                    chat_row[key] = extra[key]
        self._append_chat_row(chat_row)
        self._log_event("turn_%s" % role, turn=self._turn_idx, content=content[:80])

    def _load_history(self):
        if not os.path.isfile(self._history_path):
            return
        try:
            with open(self._history_path, "r") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                self._messages = [self._messages[0]] + [
                    {"role": m["role"], "content": m["content"]}
                    for m in data
                    if m.get("role") in ("user", "assistant") and m.get("content")
                ]
        except Exception as e:
            rospy.logwarn("Could not load history: %s", e)

    def _append_chat_row(self, row):
        data = []
        if os.path.isfile(self._history_path):
            with open(self._history_path, "r") as f:
                data = json.load(f)
        data.append(row)
        with open(self._history_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _patch_turn_affect(self, turn_idx, affect):
        """后台补写情感字段（不阻塞 TTS）。"""
        with self._lock:
            for row in self._timeline_turns:
                if row.get("turn") == turn_idx and row.get("role") == "user":
                    row.update(affect)
                    break
            self._write_timeline_doc()
        try:
            if not os.path.isfile(self._history_path):
                return
            with open(self._history_path, "r") as f:
                data = json.load(f)
            for row in data:
                if row.get("turn") == turn_idx and row.get("role") == "user":
                    for key in _AFFECT_CHAT_KEYS:
                        if key in affect:
                            row[key] = affect[key]
            with open(self._history_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            rospy.logwarn("patch turn affect: %s", e)
        self._log_event(
            "turn_affect",
            turn=turn_idx,
            emotion_visual=affect.get("emotion_visual"),
            sentiment=affect.get("sentiment"),
            affect_fused=affect.get("affect_fused"),
            cross_modal_valence_conflict=affect.get("cross_modal_valence_conflict"),
        )

    def _annotate_affect_background(self, turn_idx, text):
        try:
            from percy_affect import analyze_user_affect

            vis = (
                self._visual_tracker.current()
                if self._visual_tracker is not None
                else None
            )
            affect = analyze_user_affect(
                self._vader,
                text,
                visual_emotion=vis,
                w_vis=self._affect_w_visual,
                w_txt=self._affect_w_text,
            )
            self._patch_turn_affect(turn_idx, affect)
            rospy.loginfo(
                "Affect (async): visual=%s sentiment=%s fused=%s",
                affect["emotion_visual"],
                affect["sentiment"],
                affect["affect_fused"],
            )
        except Exception as e:
            rospy.logwarn("Affect annotation failed: %s", e)

    def _set_state(self, state):
        with self._lock:
            self._state = state
            if state == State.LISTEN:
                self._utterance_pcm = bytearray()
                self._speech_started = False
                self._speech_start_ros = None
                self._last_speech_ros = None
                self._active_streak = 0
                self._pending_start_frames = 0
        rospy.loginfo("state -> %s", state.value)

    def _state_is(self, state):
        with self._lock:
            return self._state == state

    def _amplify_pcm(self, pcm):
        gain = self._audio_gain
        if gain == 1.0 or not pcm:
            return pcm
        out = bytearray(len(pcm))
        for i in range(0, len(pcm) - 1, 2):
            s = struct.unpack_from("<h", pcm, i)[0]
            s = int(max(-32768, min(32767, round(s * gain))))
            struct.pack_into("<h", out, i, s)
        return bytes(out)

    def _init_noise_gate_threshold(self, data_root):
        if not self._enable_noise_gate:
            return 0
        if self._noise_gate_rms > 0:
            return self._noise_gate_rms
        profile_path = None
        if self._noise_gate_profile in ("__none__", "none", ""):
            profile_path = None
        elif self._noise_gate_profile not in ("__auto__", "auto"):
            profile_path = self._noise_gate_profile
        else:
            profile_path = resolve_auto_noise_profile(data_root)
        if profile_path and os.path.isfile(profile_path):
            try:
                thr = calibrate_rms_threshold_from_wav(
                    profile_path,
                    sample_rate=self._sample_rate,
                    capture_gain=self._noise_gate_capture_gain,
                    live_gain=self._audio_gain,
                    margin=self._noise_gate_margin,
                )
                rospy.loginfo(
                    "noise_gate: calibrated from %s -> rms>=%d "
                    "(capture_gain=%.1f margin=%.2f)",
                    profile_path,
                    thr,
                    self._noise_gate_capture_gain,
                    self._noise_gate_margin,
                )
                return thr
            except Exception as exc:
                rospy.logwarn("noise_gate: profile %s failed: %s", profile_path, exc)
        fallback = 1100
        rospy.logwarn(
            "noise_gate: using fallback rms>=%d (set noise_gate_profile_wav or "
            "noise_gate_rms)",
            fallback,
        )
        return fallback

    def _is_active_speech(self, frame):
        if not self._enable_noise_gate:
            try:
                return self._vad.is_speech(frame, self._sample_rate)
            except Exception:
                return False
        return is_active_speech_frame(
            self._vad,
            frame,
            self._sample_rate,
            self._noise_gate_threshold,
            speech_started=self._speech_started,
            hangover_ratio=self._noise_gate_hangover,
            start_ratio=self._noise_gate_start_ratio,
            gate_only_at_start=self._noise_gate_only_at_start,
        )

    def _frame_passes_start_gate(self, frame):
        if not self._enable_noise_gate:
            try:
                return self._vad.is_speech(frame, self._sample_rate)
            except Exception:
                return False
        from vad_noise_gate import frame_passes_energy_gate

        try:
            if not self._vad.is_speech(frame, self._sample_rate):
                return False
        except Exception:
            return False
        return frame_passes_energy_gate(
            frame, self._noise_gate_threshold, self._noise_gate_start_ratio
        )

    @staticmethod
    def _pcm_duration_sec(pcm, sample_rate):
        return float(len(pcm)) / float(2 * sample_rate)

    @staticmethod
    def _normalize_transcript(text):
        t = (text or "").strip().lower()
        while t and t[-1] in ".!?":
            t = t[:-1].strip()
        return " ".join(t.split())

    def _is_short_clip_hallucination(self, text, pcm_dur):
        if not self._reject_short_hallucinations:
            return False
        if pcm_dur >= self._short_hallucination_max_sec:
            return False
        norm = self._normalize_transcript(text)
        if not norm:
            return False
        if norm in _SHORT_WHISPER_HALLUCINATIONS:
            return True
        words = norm.split()
        if pcm_dur < 1.5 and len(words) <= 2:
            return True
        return False

    def _audio_cb(self, msg):
        if rospy.is_shutdown():
            return
        if not self._listen_enabled:
            return
        with self._lock:
            st = self._state
        if st != State.LISTEN or time.time() < self._cooldown_until:
            return
        pcm = self._amplify_pcm(bytes(msg.data))
        if self._vad_backend == "silero":
            self._process_audio_silero(pcm)
            return
        self._pcm_pending.extend(pcm)
        while len(self._pcm_pending) >= self._frame_bytes:
            frame = bytes(self._pcm_pending[: self._frame_bytes])
            del self._pcm_pending[: self._frame_bytes]
            self._process_frame_webrtc(frame)

    def _process_audio_silero(self, pcm):
        now_ros = self._now_ros()
        if self._speech_started:
            duration = now_ros - (self._speech_start_ros or now_ros)
            if duration >= self._max_utterance:
                rospy.loginfo("Max utterance %.1fs — sending to ASR", self._max_utterance)
                self._submit_utterance(
                    self._last_speech_ros or now_ros, reason="max_utterance"
                )
                return
            if duration >= 1.0 and (now_ros - self._last_listen_hint_ros) >= 3.0:
                self._last_listen_hint_ros = now_ros
                rospy.loginfo(
                    "Still listening (%.1fs) — pause ~%.1fs when done, "
                    "or: rosservice call /percy_live/end_turn \"{}\"",
                    duration,
                    self._end_silence,
                )
        for event in self._silero_stream.feed(pcm):
            self._handle_silero_event(event, now_ros)
        if self._speech_started:
            self._utterance_pcm.extend(pcm)
            self._last_speech_ros = now_ros

    def _handle_silero_event(self, event, now_ros):
        if event == "start":
            if self._speech_started:
                return
            self._speech_started = True
            self._speech_start_ros = now_ros
            self._last_speech_ros = now_ros
            self._last_listen_hint_ros = now_ros
            self._utterance_pcm = bytearray()
            rospy.loginfo("Speech start (t=%ss)", self._t_sec(now_ros))
            self._log_event("speech_start", backend="silero")
        elif event == "end" and self._speech_started:
            duration = now_ros - (self._speech_start_ros or now_ros)
            rospy.loginfo(
                "End silence (Silero) speech %.1fs — sending to ASR", duration
            )
            self._submit_utterance(
                self._last_speech_ros or now_ros, reason="end_silence"
            )

    def _process_frame_webrtc(self, frame):
        if not self._state_is(State.LISTEN) or time.time() < self._cooldown_until:
            return
        now_ros = self._now_ros()

        if not self._speech_started:
            if self._frame_passes_start_gate(frame):
                self._pending_start_frames += 1
                need = max(1, self._noise_gate_start_frames)
                if self._pending_start_frames >= need:
                    self._speech_started = True
                    self._speech_start_ros = now_ros
                    self._last_speech_ros = now_ros
                    self._last_listen_hint_ros = now_ros
                    self._utterance_pcm = bytearray()
                    self._active_streak = 0
                    self._pending_start_frames = 0
                    rospy.loginfo("Speech start (t=%ss)", self._t_sec(now_ros))
                    self._log_event("speech_start")
                    self._utterance_pcm.extend(frame)
            else:
                self._pending_start_frames = 0
            return

        is_speech = self._is_active_speech(frame)

        if is_speech:
            self._active_streak += 1
            min_af = max(1, self._noise_gate_min_active_frames)
            if (
                not self._enable_noise_gate
                or not self._noise_gate_only_at_start
                or self._active_streak >= min_af
            ):
                self._last_speech_ros = now_ros
            self._utterance_pcm.extend(frame)
            duration = now_ros - (self._speech_start_ros or now_ros)
            if duration >= self._max_utterance:
                rospy.loginfo("Max utterance %.1fs — sending to ASR", self._max_utterance)
                self._submit_utterance(
                    self._last_speech_ros or now_ros, reason="max_utterance"
                )
            return

        if not self._speech_started:
            return

        self._active_streak = 0
        self._utterance_pcm.extend(frame)
        silence = now_ros - (self._last_speech_ros or now_ros)
        duration = now_ros - (self._speech_start_ros or now_ros)
        if duration >= 1.0 and (now_ros - self._last_listen_hint_ros) >= 3.0:
            self._last_listen_hint_ros = now_ros
            rospy.loginfo(
                "Still listening (%.1fs) — pause ~%.1fs when done, "
                "or: rosservice call /percy_live/end_turn \"{}\"",
                duration,
                self._end_silence,
            )
        if silence >= self._end_silence and duration >= self._min_speech:
            rospy.loginfo(
                "End silence %.1fs (speech %.1fs) — sending to ASR",
                silence,
                duration,
            )
            self._submit_utterance(
                self._last_speech_ros or now_ros, reason="end_silence"
            )

    def _submit_utterance(self, end_ros, reason="unknown", sync=False):
        with self._lock:
            if not self._speech_started:
                return
            pcm = bytes(self._utterance_pcm)
            start_ros = self._speech_start_ros
            self._utterance_pcm = bytearray()
            self._speech_started = False
            self._speech_start_ros = None
            self._last_speech_ros = None
            self._active_streak = 0
            self._pending_start_frames = 0
        if self._silero_stream is not None:
            self._silero_stream.reset_states()
        pcm_dur = self._pcm_duration_sec(pcm, self._sample_rate)
        self._log_event(
            "utterance_end",
            reason=reason,
            duration_sec=round(pcm_dur, 3),
        )
        if pcm_dur < self._min_whisper_sec:
            rospy.logwarn("Skip ASR (clip %.2fs < min %.2fs)", pcm_dur, self._min_whisper_sec)
            return
        if self._state_is(State.PROCESS):
            rospy.logwarn("Still processing; dropped %.2fs segment", pcm_dur)
            return
        self._set_state(State.PROCESS)
        if sync:
            self._process_utterance(pcm, start_ros, end_ros)
            return
        threading.Thread(
            target=self._process_utterance,
            args=(pcm, start_ros, end_ros),
            daemon=True,
        ).start()

    def _srv_end_turn(self, _req):
        if self._speech_started and self._state_is(State.LISTEN):
            end_ros = self._now_ros()
            self._log_event("end_turn_service")
            self._submit_utterance(end_ros, reason="end_turn_service")
            return TriggerResponse(success=True, message="utterance submitted")
        return TriggerResponse(success=False, message="not listening or no speech")

    def _call_openai(self, label, fn):
        last_err = None
        for attempt in range(1, self._api_retries + 1):
            try:
                return fn()
            except Exception as e:
                last_err = e
                rospy.logwarn(
                    "%s failed (%d/%d): %s",
                    label,
                    attempt,
                    self._api_retries,
                    e,
                )
                if attempt < self._api_retries:
                    rospy.sleep(min(2.0 * attempt, 6.0))
        raise last_err

    def _compute_user_affect(self, text):
        if self._vader is None:
            return None, None
        from percy_affect import analyze_user_affect, empathy_system_note

        vis = (
            self._visual_tracker.current()
            if self._visual_tracker is not None
            else None
        )
        affect = analyze_user_affect(
            self._vader,
            text,
            visual_emotion=vis,
            w_vis=self._affect_w_visual,
            w_txt=self._affect_w_text,
        )
        note = empathy_system_note(affect) if self._enable_affect_prompt else None
        return affect, note

    def _process_utterance(self, pcm, start_ros, end_ros):
        try:
            duration_sec = self._pcm_duration_sec(pcm, self._sample_rate)
            wav_path = user_utterance_wav_path(
                self._out_dir, self._turn_idx, self._utterances_subdir
            )
            self._write_wav(wav_path, pcm)
            text = self._call_openai(
                "Whisper",
                lambda: self._transcribe(wav_path),
            )
            if not text:
                rospy.logwarn("Empty transcription (%.2fs clip)", duration_sec)
                self._set_state(State.LISTEN)
                return
            if self._is_short_clip_hallucination(text, duration_sec):
                rospy.logwarn(
                    "Skip ASR (likely Whisper hallucination on %.2fs): %s",
                    duration_sec,
                    text,
                )
                self._set_state(State.LISTEN)
                return
            rospy.loginfo("You said: %s", text)
            user_extra = {"wav": wav_path, "source": "live_vad"}
            affect_note = None
            user_turn = self._turn_idx

            if self._topic_manager is not None:
                turn_on_topic = self._topic_manager.on_user_turn()
                if self._topic_manager.should_wrap_up_topic():
                    from percy_profile import TOPIC_WRAP_UP_NOTE

                    self._messages.append(
                        {"role": "system", "content": TOPIC_WRAP_UP_NOTE}
                    )
                rospy.logdebug(
                    "Profile topic turn %d/%d",
                    turn_on_topic,
                    self._topic_manager.followups_per_topic,
                )

            use_sync_affect = self._vader is not None and (
                self._enable_affect_prompt or not self._affect_async
            )
            if use_sync_affect:
                affect, affect_note = self._compute_user_affect(text)
                if affect:
                    user_extra.update(affect)
                    rospy.loginfo(
                        "Affect: visual=%s sentiment=%s(%.2f) fused=%s conflict=%s",
                        affect["emotion_visual"],
                        affect["sentiment"],
                        affect["sentiment_score"],
                        affect["affect_fused"],
                        affect["cross_modal_valence_conflict"],
                    )
                    self._log_event(
                        "turn_affect",
                        turn=user_turn,
                        emotion_visual=affect["emotion_visual"],
                        sentiment=affect["sentiment"],
                        affect_fused=affect["affect_fused"],
                        cross_modal_valence_conflict=affect["cross_modal_valence_conflict"],
                    )

            self._commit_turn(
                "user",
                text,
                start_ros,
                end_ros,
                extra=user_extra,
            )
            self._messages.append({"role": "user", "content": text})

            if self._vader is not None and self._affect_async and not self._enable_affect_prompt:
                threading.Thread(
                    target=self._annotate_affect_background,
                    args=(user_turn, text),
                    daemon=True,
                ).start()

            topic_change_turn = (
                self._topic_manager is not None
                and self._topic_manager.should_change_topic()
            )

            if topic_change_turn:
                from percy_profile import TOPIC_WRAP_UP_NOTE, sanitize_wrap_up_reply

                wrap_reply = self._call_openai(
                    "GPT wrap-up",
                    lambda: self._chat(
                        affect_note=affect_note,
                        extra_system=TOPIC_WRAP_UP_NOTE,
                        max_tokens=50,
                        temperature=0.5,
                    ),
                )
                wrap_reply = sanitize_wrap_up_reply(wrap_reply)
                question, answer = self._topic_manager.change_topic()
                if question and answer:
                    intro_note = self._topic_manager.build_topic_intro_note(
                        question, answer
                    )
                    self._messages.extend(
                        self._topic_manager.build_topic_change_messages(
                            question, answer
                        )
                    )
                    topic_reply = self._call_openai(
                        "GPT new topic",
                        lambda: self._chat(
                            extra_system=intro_note,
                            max_tokens=90,
                            temperature=0.6,
                        ),
                    )
                    reply = wrap_reply or ""
                    if topic_reply:
                        reply = (reply + " " + topic_reply).strip()
                    rospy.loginfo(
                        "Profile topic changed (%d topics remaining)",
                        self._topic_manager.topics_remaining,
                    )
                else:
                    reply = wrap_reply
                    rospy.loginfo("All profile topics discussed")
                self._topic_manager.reset_topic_counter()
            else:
                reply = self._call_openai(
                    "GPT",
                    lambda: self._chat(affect_note=affect_note),
                )

            if not reply:
                rospy.logwarn("Empty GPT reply")
                self._set_state(State.LISTEN)
                return

            rospy.loginfo("PERCY: %s", reply)
            self._speak(reply, is_greeting=False)
        except Exception as e:
            rospy.logerr("process_utterance: %s", e)
            import traceback

            traceback.print_exc()
            self._set_state(State.LISTEN)

    def _write_wav(self, path, pcm):
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm)

    def _transcribe(self, wav_path):
        with open(wav_path, "rb") as f:
            tr = self._openai.audio.transcriptions.create(
                model=self._whisper_model,
                file=f,
                language="en",
            )
        return (tr.text or "").strip()

    def _chat(
        self,
        affect_note=None,
        extra_system=None,
        max_tokens=120,
        temperature=0.7,
    ):
        messages = list(self._messages)
        if affect_note and self._enable_affect_prompt:
            messages = messages + [
                {"role": "system", "content": affect_note},
            ]
        if extra_system:
            messages.append({"role": "system", "content": extra_system})
        chat = self._openai.chat.completions.create(
            model=self._chat_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        reply = (chat.choices[0].message.content or "").strip()
        self._messages.append({"role": "assistant", "content": reply})
        return reply

    def _speak(self, text, is_greeting=False):
        with self._lock:
            self._state = State.SPEAK
            self._utterance_pcm = bytearray()
            self._pcm_pending = bytearray()
            self._speech_started = False
            self._pending_start_frames = 0
        self._tts_start_ros = self._now_ros()
        self._pending_assistant = {"text": text, "is_greeting": is_greeting}
        goal = TtsGoal()
        goal.rawtext.lang_id = "en_GB"
        goal.rawtext.text = text
        self._tts.send_goal(goal, done_cb=self._tts_done_cb)
        rospy.loginfo("TTS sent (%d chars): %s", len(text), text[:60])

    def _tts_done_cb(self, state, result):
        if state != GoalStatus.SUCCEEDED:
            rospy.logerr("TTS action failed state=%s result=%s", state, result)
        else:
            rospy.loginfo("TTS action SUCCEEDED (PAL result received)")

    def _tts_feedback(self, feedback):
        if feedback.feedback.event_type != TtsFeedback.TTS_EVENT_FINISHED_PLAYING_UTTERANCE:
            return
        if not self._state_is(State.SPEAK):
            return
        end_ros = self._now_ros()
        pending = getattr(self, "_pending_assistant", None)
        start_ros = getattr(self, "_tts_start_ros", None)
        if pending and start_ros is not None:
            dur = end_ros - start_ros
            rospy.loginfo(
                "TTS playback finished (%.2fs): %s",
                dur,
                (pending.get("text") or "")[:80],
            )
            self._commit_turn(
                "assistant",
                pending["text"],
                self._tts_start_ros,
                end_ros,
                extra={"source": "tts", "is_greeting": pending.get("is_greeting", False)},
            )
        self._pending_assistant = None
        self._tts_start_ros = None
        with self._lock:
            self._cooldown_until = time.time() + self._post_tts_mute
            self._pcm_pending = bytearray()
        self._turn_idx += 1
        self._set_state(State.COOLDOWN)
        rospy.Timer(
            rospy.Duration(self._post_tts_mute),
            self._cooldown_done,
            oneshot=True,
        )

    def _cooldown_done(self, _event):
        if self._state_is(State.COOLDOWN):
            self._listen_enabled = True
            self._set_state(State.LISTEN)
            rospy.loginfo("Ready — speak (pause ~%.1fs to end turn)", self._end_silence)

    def _on_shutdown(self):
        with self._lock:
            if not self._speech_started:
                return
            end_ros = self._last_speech_ros or self._now_ros()
        if not self._state_is(State.PROCESS):
            rospy.loginfo("Shutdown: flushing in-progress speech to ASR …")
            self._submit_utterance(end_ros, reason="shutdown_flush", sync=True)


def main():
    LiveDialogue()
    rospy.spin()


if __name__ == "__main__":
    main()
