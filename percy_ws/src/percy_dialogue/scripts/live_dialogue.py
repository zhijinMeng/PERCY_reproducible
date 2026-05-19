#!/usr/bin/env python3
"""
Real-time turn-taking dialogue for PERCY benchmark.

  USB mic (/audio/rode) + robot TTS; optional stamp-aligned A/V in parallel.

Design:
  - WebRTC VAD end-of-utterance (no energy/window hacks)
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
from actionlib import SimpleActionClient
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


class State(enum.Enum):
    LISTEN = "listen"
    PROCESS = "process"
    SPEAK = "speak"
    COOLDOWN = "cooldown"


class LiveDialogue(object):
    FRAME_MS = 30

    def __init__(self):
        rospy.init_node("live_dialogue")

        self._session_id = str(rospy.get_param("~session_id", "0"))
        self._audio_topic = rospy.get_param("~audio_topic", "/audio/rode")
        self._sample_rate = int(rospy.get_param("~sample_rate", 16000))
        self._vad_mode = int(rospy.get_param("~vad_mode", 3))
        self._audio_gain = float(rospy.get_param("~audio_gain", 2.0))
        self._end_silence = float(rospy.get_param("~end_silence_sec", 0.8))
        self._min_speech = float(rospy.get_param("~min_speech_sec", 0.35))
        self._min_whisper_sec = float(rospy.get_param("~min_whisper_sec", 0.5))
        self._max_utterance = float(rospy.get_param("~max_utterance_sec", 12.0))
        self._api_retries = int(rospy.get_param("~openai_retries", 3))
        self._post_tts_mute = float(rospy.get_param("~post_tts_mute_sec", 1.2))
        self._whisper_model = str(rospy.get_param("~whisper_model", "whisper-1"))
        self._chat_model = str(rospy.get_param("~chat_model", "gpt-4o-mini"))
        self._play_greeting = bool(rospy.get_param("~play_greeting", True))
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

        self._vad = webrtcvad.Vad(self._vad_mode)
        self._frame_bytes = int(self._sample_rate * self.FRAME_MS / 1000) * 2

        self._lock = threading.Lock()
        self._state = State.LISTEN
        self._pcm_pending = bytearray()
        self._utterance_pcm = bytearray()
        self._speech_started = False
        self._speech_start_ros = None
        self._last_speech_ros = None
        self._cooldown_until = 0.0
        self._listen_enabled = False
        self._turn_idx = 0
        self._timeline_turns = []

        self._t0_ros = None
        self._t0_source = None

        self._messages = [
            {
                "role": "system",
                "content": (
                    "You are PERCY, a friendly social robot. "
                    "Short spoken replies: one or two sentences, simple English."
                ),
            }
        ]
        self._load_history()

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
            "live_dialogue: session=%s audio=%s t0=%.3f (%s) vad=%d gain=%.1f "
            "end_silence=%.2fs out=%s utterances=%s",
            self._session_id,
            self._audio_topic,
            self._t0_ros or -1,
            self._t0_source,
            self._vad_mode,
            self._audio_gain,
            self._end_silence,
            self._out_dir,
            self._utterances_dir,
        )
        self._log_event("node_ready")

        if self._play_greeting:
            with self._lock:
                self._state = State.SPEAK
            self._speak(self._greeting, is_greeting=True)
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

    def _set_state(self, state):
        with self._lock:
            self._state = state
            if state == State.LISTEN:
                self._utterance_pcm = bytearray()
                self._speech_started = False
                self._speech_start_ros = None
                self._last_speech_ros = None
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

    @staticmethod
    def _pcm_duration_sec(pcm, sample_rate):
        return float(len(pcm)) / float(2 * sample_rate)

    def _audio_cb(self, msg):
        if rospy.is_shutdown():
            return
        if not self._listen_enabled:
            return
        with self._lock:
            st = self._state
        if st != State.LISTEN or time.time() < self._cooldown_until:
            return
        chunk = bytes(msg.data)
        self._pcm_pending.extend(chunk)
        while len(self._pcm_pending) >= self._frame_bytes:
            frame = bytes(self._pcm_pending[: self._frame_bytes])
            del self._pcm_pending[: self._frame_bytes]
            self._process_frame(self._amplify_pcm(frame))

    def _process_frame(self, frame):
        if not self._state_is(State.LISTEN) or time.time() < self._cooldown_until:
            return
        now_ros = self._now_ros()
        try:
            is_speech = self._vad.is_speech(frame, self._sample_rate)
        except Exception:
            return

        if is_speech:
            if not self._speech_started:
                self._speech_started = True
                self._speech_start_ros = now_ros
                self._utterance_pcm = bytearray()
                rospy.loginfo("Speech start (t=%ss)", self._t_sec(now_ros))
                self._log_event("speech_start")
            self._last_speech_ros = now_ros
            self._utterance_pcm.extend(frame)
            duration = now_ros - (self._speech_start_ros or now_ros)
            if duration >= self._max_utterance:
                rospy.loginfo("Max utterance %.1fs — sending to ASR", self._max_utterance)
                self._submit_utterance(self._last_speech_ros or now_ros)
            return

        if not self._speech_started:
            return

        self._utterance_pcm.extend(frame)
        silence = now_ros - (self._last_speech_ros or now_ros)
        duration = now_ros - (self._speech_start_ros or now_ros)
        if silence >= self._end_silence and duration >= self._min_speech:
            self._submit_utterance(self._last_speech_ros or now_ros)

    def _submit_utterance(self, end_ros):
        with self._lock:
            if not self._speech_started:
                return
            pcm = bytes(self._utterance_pcm)
            start_ros = self._speech_start_ros
            self._utterance_pcm = bytearray()
            self._speech_started = False
            self._speech_start_ros = None
            self._last_speech_ros = None
        pcm_dur = self._pcm_duration_sec(pcm, self._sample_rate)
        if pcm_dur < self._min_whisper_sec:
            rospy.logwarn("Skip ASR (%.2fs)", pcm_dur)
            return
        if self._state_is(State.PROCESS):
            rospy.logwarn("Still processing; dropped %.2fs segment", pcm_dur)
            return
        self._set_state(State.PROCESS)
        threading.Thread(
            target=self._process_utterance,
            args=(pcm, start_ros, end_ros),
            daemon=True,
        ).start()

    def _srv_end_turn(self, _req):
        if self._speech_started and self._state_is(State.LISTEN):
            end_ros = self._now_ros()
            self._log_event("end_turn_service")
            self._submit_utterance(end_ros)
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
                rospy.logwarn("Empty transcription")
                self._set_state(State.LISTEN)
                return
            rospy.loginfo("You said: %s", text)
            self._commit_turn(
                "user",
                text,
                start_ros,
                end_ros,
                extra={"wav": wav_path, "source": "live_vad"},
            )
            self._messages.append({"role": "user", "content": text})

            reply = self._call_openai("GPT", self._chat)
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

    def _chat(self):
        chat = self._openai.chat.completions.create(
            model=self._chat_model,
            messages=self._messages,
            max_tokens=120,
            temperature=0.7,
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
        self._tts_start_ros = self._now_ros()
        self._pending_assistant = {"text": text, "is_greeting": is_greeting}
        goal = TtsGoal()
        goal.rawtext.lang_id = "en_GB"
        goal.rawtext.text = text
        self._tts.send_goal(goal)
        rospy.loginfo("TTS sent (%d chars)", len(text))

    def _tts_feedback(self, feedback):
        if feedback.feedback.event_type != TtsFeedback.TTS_EVENT_FINISHED_PLAYING_UTTERANCE:
            return
        if not self._state_is(State.SPEAK):
            return
        end_ros = self._now_ros()
        pending = getattr(self, "_pending_assistant", None)
        if pending and getattr(self, "_tts_start_ros", None) is not None:
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
            pcm = bytes(self._utterance_pcm)
            start_ros = self._speech_start_ros
            end_ros = self._last_speech_ros or self._now_ros()
        if self._pcm_duration_sec(pcm, self._sample_rate) >= self._min_whisper_sec:
            self._log_event("shutdown_flush")
            if not self._state_is(State.PROCESS):
                self._submit_utterance(end_ros)


def main():
    LiveDialogue()
    rospy.spin()


if __name__ == "__main__":
    main()
