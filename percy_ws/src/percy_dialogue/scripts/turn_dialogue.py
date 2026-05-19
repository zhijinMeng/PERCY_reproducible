#!/usr/bin/env python3
"""
Turn-taking dialogue (onboard /audio/channel0) with benchmark timeline annotations.

Writes per session:
  chat_history.json       — dialogue text (list of turns)
  dialogue_timeline.json  — same turns with t_start_sec / t_end_sec vs recording

Timeline origin = recording_meta.first_image_stamp (same as audio.wav t=0).
"""
from __future__ import print_function

import enum
import json
import os
import struct
import sys

# 优先从本脚本目录 import 模块（避免 devel/lib 里旧的 session_timeline 包装器）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import threading
import time
import wave

import rospy
import webrtcvad
from actionlib import SimpleActionClient
from audio_common_msgs.msg import AudioData
from openai import OpenAI
from pal_interaction_msgs.msg import TtsAction, TtsGoal, TtsFeedback

from session_timeline import SessionTimeline, default_data_root
from percy_affect import (
    VisualEmotionTracker,
    analyze_user_affect,
    empathy_system_note,
    load_vader_analyzer,
)


class State(enum.Enum):
    LISTEN = "listen"
    PROCESS = "process"
    SPEAK = "speak"
    COOLDOWN = "cooldown"


# Whisper 在短杂音上常幻觉出的词
_SPURIOUS_WORDS = frozenset(
    {"you", "uh", "um", "hmm", "hm", "ah", "oh", "the", "a", "i", "it", "that"}
)
# 允许的单字/短词（有意说出的）
_ALLOW_SHORT_WORDS = frozenset(
    {"yes", "no", "hi", "hey", "stop", "help", "wait", "ok", "okay", "yeah", "yep", "nope"}
)
# 静音/杂音上 Whisper 常见幻觉（YouTube 片尾套话等）
_HALLUCINATION_PHRASES = (
    "thanks for watching",
    "thank you for watching",
    "thanks for listening",
    "please subscribe",
    "like and subscribe",
    "see you next time",
    "subtitles by",
    "amara.org",
    "transcribe only what the person",
    "what the person actually said",
)


class TurnDialogue(object):
    FRAME_MS = 30

    def __init__(self):
        rospy.init_node("turn_dialogue")

        self._session_id = str(rospy.get_param("~session_id", "0"))
        self._audio_topic = rospy.get_param("~audio_topic", "/audio/channel0")
        self._sample_rate = int(rospy.get_param("~sample_rate", 16000))
        # VAD 0–3：数字越小越灵敏；3 太严容易要大喊才触发
        self._vad_mode = int(rospy.get_param("~vad_mode", 1))
        self._audio_gain = float(rospy.get_param("~audio_gain", 2.0))
        # 句内短暂停顿不要立刻截断；默认 1.4s 静音才结束一轮
        self._end_silence = float(rospy.get_param("~end_silence_sec", 1.4))
        self._min_speech = float(rospy.get_param("~min_speech_sec", 0.5))
        # 低于此时长不调用 Whisper（避免 ~1s 杂音 you 各耗 1–2s API）
        self._min_whisper_sec = float(rospy.get_param("~min_whisper_sec", 1.0))
        self._min_words = int(rospy.get_param("~min_transcript_words", 2))
        self._reject_spurious = bool(rospy.get_param("~reject_spurious_transcripts", True))
        self._max_utterance = float(rospy.get_param("~max_utterance_sec", 25.0))
        self._post_tts_mute = float(rospy.get_param("~post_tts_mute_sec", 1.2))
        self._whisper_model = str(rospy.get_param("~whisper_model", "whisper-1"))
        self._chat_model = str(rospy.get_param("~chat_model", "gpt-4o-mini"))
        self._enable_vader = bool(rospy.get_param("~enable_vader", True))
        self._enable_visual_affect = bool(rospy.get_param("~enable_visual_affect", False))
        self._fusion_w_visual = float(rospy.get_param("~fusion_w_visual", 0.6))
        self._fusion_w_text = float(rospy.get_param("~fusion_w_text", 0.4))
        self._play_greeting = bool(rospy.get_param("~play_greeting", True))
        self._greeting = str(
            rospy.get_param(
                "~greeting_text",
                "Hello! I am PERCY. Say something, and I will reply.",
            )
        )
        self._timeline_timeout = float(rospy.get_param("~timeline_origin_timeout_sec", 60.0))

        data_root = rospy.get_param("~data_root", "__auto__")
        if not data_root or data_root == "__auto__":
            data_root = default_data_root()

        self._timeline = SessionTimeline(self._session_id, data_root)
        self._out_dir = self._timeline.out_dir
        self._history_path = os.path.join(self._out_dir, "chat_history.json")
        self._turn_idx = 0
        self._pending_assistant = None
        self._tts_start_ros = None

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            rospy.logfatal("OPENAI_API_KEY not set")
            sys.exit(1)
        self._openai = OpenAI(api_key=api_key)

        self._vader = load_vader_analyzer() if self._enable_vader else None
        self._visual_tracker = (
            VisualEmotionTracker() if self._enable_visual_affect else None
        )
        if self._enable_vader:
            rospy.loginfo(
                "VADER on (fusion w_vis=%.2f w_txt=%.2f); visual=%s",
                self._fusion_w_visual,
                self._fusion_w_text,
                self._enable_visual_affect,
            )

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
        self._queued_utterance = None  # (pcm, start_ros, end_ros)，PROCESS 期间最多缓存 1 段
        self._last_user_text_norm = None  # 防同一句被 process + queue 处理两次

        self._messages = [
            {
                "role": "system",
                "content": (
                    "You are PERCY, a friendly social robot. "
                    "Have a short spoken dialogue: one or two sentences per turn, "
                    "simple words, empathetic tone. English only."
                ),
            }
        ]
        self._load_history()

        self._tts = SimpleActionClient("/tts", TtsAction)
        rospy.loginfo("Waiting for /tts ...")
        self._tts.wait_for_server()
        rospy.Subscriber("/tts/feedback", TtsFeedback, self._tts_feedback, queue_size=20)

        # 先锁定时间轴原点，再订阅音频（resolve 期间 rospy.sleep 会处理回调）
        self._timeline.resolve_origin(timeout_sec=self._timeline_timeout)
        rospy.Subscriber(
            self._audio_topic, AudioData, self._audio_cb, queue_size=200, buff_size=2**20
        )

        rospy.loginfo(
            "turn_dialogue: session=%s audio=%s out=%s t0=%.3f (%s) vad=%d gain=%.1f",
            self._session_id,
            self._audio_topic,
            self._out_dir,
            self._timeline.t0_ros or -1,
            self._timeline.t0_source,
            self._vad_mode,
            self._audio_gain,
        )

        if self._play_greeting:
            with self._lock:
                self._state = State.SPEAK
            self._speak(self._greeting, is_greeting=True)

    @staticmethod
    def _now_ros():
        return rospy.Time.now().to_sec()

    def _fmt_t(self, ros_sec):
        t = self._timeline.t_sec(ros_sec)
        return "%.2f" % t if t is not None else "?"

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

    def _accept_transcript(self, text, duration_sec):
        if not self._reject_spurious:
            return True, ""
        text = (text or "").strip()
        if not text:
            return False, "empty"
        if duration_sec < self._min_speech * 0.85:
            return False, "audio_too_short"
        norm = text.lower().strip(".,!?;:\"'")
        words = norm.split()
        if norm in _SPURIOUS_WORDS:
            return False, "blocklist"
        for phrase in _HALLUCINATION_PHRASES:
            if phrase in norm:
                return False, "hallucination_phrase"
        if len(words) == 1:
            w = words[0]
            if w in _ALLOW_SHORT_WORDS:
                return True, ""
            if len(w) <= 4:
                return False, "single_short_word"
        if len(words) < self._min_words:
            return False, "min_words"
        return True, ""

    def _is_duplicate_user_text(self, text):
        norm = " ".join((text or "").lower().split())
        if not norm or not self._last_user_text_norm:
            return False
        if norm == self._last_user_text_norm:
            return True
        if len(norm) > 12 and len(self._last_user_text_norm) > 12:
            if norm in self._last_user_text_norm or self._last_user_text_norm in norm:
                return True
        return False

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

    def _commit_turn(self, role, content, t_start_ros, t_end_ros, extra=None):
        row = {
            "turn": self._turn_idx,
            "role": role,
            "content": content,
            "t_start_sec": self._timeline.t_sec(t_start_ros),
            "t_end_sec": self._timeline.t_sec(t_end_ros),
            "t_start_ros": t_start_ros,
            "t_end_ros": t_end_ros,
        }
        if extra:
            row.update(extra)
        self._timeline.add_turn(row)
        chat_row = {
            "turn": row["turn"],
            "role": role,
            "content": content,
            "t_start_sec": row["t_start_sec"],
            "t_end_sec": row["t_end_sec"],
        }
        if extra:
            for key in (
                "emotion_visual",
                "sentiment",
                "sentiment_score",
                "affect_fused",
                "affect_fused_confidence",
                "affect_fusion_weights",
                "affect_fused_distribution",
            ):
                if key in extra:
                    chat_row[key] = extra[key]
        self._append_chat_row(chat_row)

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

    def _reset_utterance_buffer(self):
        with self._lock:
            self._utterance_pcm = bytearray()
            self._speech_started = False
            self._speech_start_ros = None
            self._last_speech_ros = None

    def _return_to_listen(self):
        self._set_state(State.LISTEN)
        self._drain_queued_utterance()

    def _drain_queued_utterance(self):
        with self._lock:
            item = self._queued_utterance
            self._queued_utterance = None
        if not item:
            return
        pcm, start_ros, end_ros = item
        pcm_dur = self._pcm_duration_sec(pcm, self._sample_rate)
        if pcm_dur < self._min_whisper_sec:
            rospy.logwarn("Dropped queued segment (%.2fs)", pcm_dur)
            return
        rospy.loginfo("Processing queued utterance (%.2fs)", pcm_dur)
        self._set_state(State.PROCESS)
        threading.Thread(
            target=self._process_utterance,
            args=(pcm, start_ros, end_ros),
            daemon=True,
        ).start()

    def _audio_cb(self, msg):
        if rospy.is_shutdown():
            return
        with self._lock:
            st = self._state
        if st == State.SPEAK:
            return
        if st == State.LISTEN and time.time() < self._cooldown_until:
            return
        if st not in (State.LISTEN, State.PROCESS):
            return
        chunk = bytes(msg.data)
        self._pcm_pending.extend(chunk)
        while len(self._pcm_pending) >= self._frame_bytes:
            frame = bytes(self._pcm_pending[: self._frame_bytes])
            del self._pcm_pending[: self._frame_bytes]
            self._process_frame(self._amplify_pcm(frame))

    def _process_frame(self, frame):
        with self._lock:
            st = self._state
        if st not in (State.LISTEN, State.PROCESS):
            return
        if st == State.LISTEN and time.time() < self._cooldown_until:
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
                rospy.loginfo("Speech start (t=%ss)", self._fmt_t(now_ros))
            self._last_speech_ros = now_ros
            self._utterance_pcm.extend(frame)
            return

        if not self._speech_started:
            return

        self._utterance_pcm.extend(frame)
        silence = now_ros - (self._last_speech_ros or now_ros)
        duration = now_ros - (self._speech_start_ros or now_ros)
        if silence >= self._end_silence and duration >= self._min_speech:
            pcm = bytes(self._utterance_pcm)
            pcm_dur = self._pcm_duration_sec(pcm, self._sample_rate)
            if pcm_dur < self._min_whisper_sec:
                rospy.logwarn(
                    "Ignored short segment (%.2fs < %.2fs), skip ASR",
                    pcm_dur,
                    self._min_whisper_sec,
                )
                self._reset_utterance_buffer()
                return
            start_ros = self._speech_start_ros
            end_ros = self._last_speech_ros or now_ros
            if self._state_is(State.PROCESS):
                with self._lock:
                    if self._queued_utterance is None:
                        self._queued_utterance = (pcm, start_ros, end_ros)
                        rospy.loginfo(
                            "Queued speech during PROCESS (%.2fs); will run after current turn",
                            pcm_dur,
                        )
                    else:
                        rospy.logwarn(
                            "Speech during PROCESS dropped (queue full, %.2fs)",
                            pcm_dur,
                        )
                self._reset_utterance_buffer()
                return
            # 立刻清空 VAD，避免同一段语音在 PROCESS 中再次 end → queue 重复识别
            self._reset_utterance_buffer()
            self._set_state(State.PROCESS)
            threading.Thread(
                target=self._process_utterance,
                args=(pcm, start_ros, end_ros),
                daemon=True,
            ).start()

    def _process_utterance(self, pcm, start_ros, end_ros):
        try:
            duration_sec = self._pcm_duration_sec(pcm, self._sample_rate)
            if duration_sec < self._min_whisper_sec:
                rospy.logwarn("Skip ASR (%.2fs)", duration_sec)
                self._return_to_listen()
                return
            wav_path = os.path.join(self._out_dir, "utterance_%04d.wav" % self._turn_idx)
            self._write_wav(wav_path, pcm)
            text = self._transcribe(wav_path)
            if not text:
                rospy.logwarn("Empty transcription, listening again")
                self._return_to_listen()
                return
            ok, reason = self._accept_transcript(text, duration_sec)
            if not ok:
                rospy.logwarn(
                    "Ignored transcription (%s, %.2fs audio): %r",
                    reason,
                    duration_sec,
                    text,
                )
                self._return_to_listen()
                return
            if self._is_duplicate_user_text(text):
                rospy.logwarn("Duplicate user speech ignored: %r", text)
                self._return_to_listen()
                return
            self._last_user_text_norm = " ".join(text.lower().split())
            rospy.loginfo("You said: %s", text)

            affect_extra = {}
            affect_note = None
            if self._vader is not None:
                vis = (
                    self._visual_tracker.current()
                    if self._visual_tracker is not None
                    else None
                )
                affect = analyze_user_affect(
                    self._vader,
                    text,
                    visual_emotion=vis,
                    w_vis=self._fusion_w_visual,
                    w_txt=self._fusion_w_text,
                )
                affect_extra = affect
                affect_note = empathy_system_note(affect)
                rospy.loginfo(
                    "Affect: visual=%s sentiment=%s(%.2f) fused=%s",
                    affect["emotion_visual"],
                    affect["sentiment"],
                    affect["sentiment_score"],
                    affect["affect_fused"],
                )

            user_extra = {"wav": wav_path, "source": "vad_segment"}
            user_extra.update(affect_extra)
            self._commit_turn(
                "user",
                text,
                start_ros,
                end_ros,
                extra=user_extra,
            )
            chat_row = {
                "turn": self._turn_idx,
                "role": "user",
                "content": text,
                "t_start_sec": self._timeline.t_sec(start_ros),
                "t_end_sec": self._timeline.t_sec(end_ros),
            }
            self._messages.append({"role": "user", "content": text})

            reply = self._chat(affect_note=affect_note)
            if not reply:
                rospy.logwarn("Empty GPT reply")
                self._return_to_listen()
                return
            rospy.loginfo("PERCY: %s", reply)
            self._speak(reply, is_greeting=False)
        except Exception as e:
            rospy.logerr("process_utterance: %s", e)
            import traceback

            traceback.print_exc()
            self._return_to_listen()

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
                prompt="Casual English chat with a person near a robot.",
            )
        text = (tr.text or "").strip()
        if len(text.split()) < 1:
            return ""
        return text

    def _chat(self, affect_note=None):
        messages = list(self._messages)
        if affect_note:
            messages = messages + [
                {"role": "system", "content": affect_note},
            ]
        chat = self._openai.chat.completions.create(
            model=self._chat_model,
            messages=messages,
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
        self._pending_assistant = {
            "text": text,
            "is_greeting": is_greeting,
            "turn": self._turn_idx,
        }
        goal = TtsGoal()
        goal.rawtext.lang_id = "en_GB"
        goal.rawtext.text = text
        self._tts.send_goal(goal)
        rospy.loginfo("TTS sent (%d chars) t=%ss", len(text), self._fmt_t(self._tts_start_ros))

    def _tts_feedback(self, feedback):
        if feedback.feedback.event_type != TtsFeedback.TTS_EVENT_FINISHED_PLAYING_UTTERANCE:
            return
        if not self._state_is(State.SPEAK):
            return
        end_ros = self._now_ros()
        pending = self._pending_assistant
        if pending and self._tts_start_ros is not None:
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
            self._utterance_pcm = bytearray()
        self._turn_idx += 1
        self._set_state(State.LISTEN)
        rospy.loginfo(
            "TTS done; %.2fs echo guard — wait for Ready before speaking",
            self._post_tts_mute,
        )
        rospy.Timer(rospy.Duration(self._post_tts_mute), self._ready_after_mute, oneshot=True)

    def _ready_after_mute(self, _event):
        if self._state_is(State.LISTEN) and time.time() >= self._cooldown_until:
            rospy.loginfo("Ready for your next turn.")
            self._drain_queued_utterance()


def main():
    TurnDialogue()
    rospy.spin()


if __name__ == "__main__":
    main()
