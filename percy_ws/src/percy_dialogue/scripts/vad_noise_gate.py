#!/usr/bin/env python3
"""RMS noise gate helpers for live_dialogue WebRTC VAD."""
from __future__ import print_function

import math
import os
import struct
import statistics
import wave

FRAME_MS = 30


def frame_rms_int16(frame):
    n = len(frame) // 2
    if n == 0:
        return 0.0
    ss = 0.0
    for i in range(0, len(frame), 2):
        s = struct.unpack_from("<h", frame, i)[0]
        ss += float(s * s)
    return math.sqrt(ss / n)


def amplify_pcm_int16(pcm, gain):
    if gain == 1.0 or not pcm:
        return pcm
    out = bytearray(len(pcm))
    for i in range(0, len(pcm) - 1, 2):
        s = struct.unpack_from("<h", pcm, i)[0]
        s = int(max(-32768, min(32767, round(s * gain))))
        struct.pack_into("<h", out, i, s)
    return bytes(out)


def calibrate_rms_threshold_from_wav(
    wav_path,
    sample_rate=16000,
    capture_gain=2.5,
    live_gain=1.2,
    margin=1.35,
    percentile=0.90,
):
    """Estimate gate from raw mic ambient recording (pre-ROS)."""
    with wave.open(wav_path, "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("need 16-bit PCM")
        sr = wf.getframerate()
        if sr != sample_rate:
            raise ValueError("expected sr=%d got %d" % (sample_rate, sr))
        pcm = wf.readframes(wf.getnframes())
    pcm = amplify_pcm_int16(pcm, capture_gain)
    pcm = amplify_pcm_int16(pcm, live_gain)
    frame_bytes = int(sample_rate * FRAME_MS / 1000) * 2
    rms_vals = []
    for off in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
        rms_vals.append(frame_rms_int16(pcm[off : off + frame_bytes]))
    if not rms_vals:
        return 0
    idx = max(0, min(len(rms_vals) - 1, int(round(percentile * (len(rms_vals) - 1)))))
    sorted_rms = sorted(rms_vals)
    base = sorted_rms[idx]
    return int(max(1.0, round(base * margin)))


def resolve_auto_noise_profile(data_root):
    if not data_root:
        return None
    candidates = [
        os.path.join(data_root, "lab_ambient_day_29", "ambient_raw.wav"),
        os.path.join(data_root, "lab_ambient", "ambient_raw.wav"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def frame_passes_energy_gate(frame, gate_rms, ratio=0.65):
    if gate_rms <= 0:
        return True
    return frame_rms_int16(frame) >= float(gate_rms) * ratio


def is_active_speech_frame(
    vad,
    frame,
    sample_rate,
    gate_rms,
    speech_started=False,
    hangover_ratio=1.0,
    start_ratio=0.65,
    gate_only_at_start=False,
):
    """WebRTC VAD; optional RMS gate only before utterance is open."""
    try:
        vad_speech = vad.is_speech(frame, sample_rate)
    except Exception:
        return False
    if not vad_speech:
        return False
    if gate_rms <= 0:
        return True
    if gate_only_at_start and speech_started:
        return True
    ratio = start_ratio if (not speech_started or gate_only_at_start) else hangover_ratio
    return frame_passes_energy_gate(frame, gate_rms, ratio)
