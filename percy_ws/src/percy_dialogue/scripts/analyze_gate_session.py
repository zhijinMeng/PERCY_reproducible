#!/usr/bin/env python3
"""Analyze VAD+noise gate on a session audio.wav (post-rode, apply live_gain only)."""
import os
import statistics
import struct
import sys
import wave

import webrtcvad

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from vad_noise_gate import amplify_pcm_int16, frame_rms_int16, is_active_speech_frame

path = sys.argv[1] if len(sys.argv) > 1 else "/workspace/percy_data/29/audio.wav"
t_start = float(sys.argv[2]) if len(sys.argv) > 2 else 8.0
t_end = float(sys.argv[3]) if len(sys.argv) > 3 else 26.0
gain = float(os.environ.get("AUDIO_GAIN", "1.2"))
gate = int(os.environ.get("NOISE_GATE_RMS", "1119"))

with wave.open(path) as w:
    sr = w.getframerate()
    pcm = w.readframes(w.getnframes())

dur = len(pcm) / (2 * sr)
print("file=%s duration=%.1fs gain=%.1f gate=%d" % (path, dur, gain, gate))

vad = webrtcvad.Vad(int(os.environ.get("VAD_MODE", "2")))
fb = int(sr * 0.03) * 2
seg = pcm[int(t_start * sr * 2) : int(t_end * sr * 2)]

vad_only = gate_act = vad_not = total = 0
max_sil = cur = 0
rms_vad = []
for off in range(0, len(seg) - fb + 1, fb):
    frame = amplify_pcm_int16(seg[off : off + fb], gain)
    total += 1
    vad_s = vad.is_speech(frame, sr)
    active = is_active_speech_frame(
        vad,
        frame,
        sr,
        gate,
        speech_started=True,
        hangover_ratio=float(os.environ.get("HANGOVER", "1.0")),
        start_ratio=float(os.environ.get("START_RATIO", "0.5")),
    )
    if vad_s:
        vad_only += 1
        rms_vad.append(frame_rms_int16(frame))
    if active:
        gate_act += 1
        cur = 0
    else:
        cur += 1
        max_sil = max(max_sil, cur)
    if vad_s and not active:
        vad_not += 1

print("segment %.1f-%.1fs frames=%d" % (t_start, t_end, total))
print(
    "vad=%.1f%% gate_active=%.1f%% vad_blocked=%.1f%%"
    % (100 * vad_only / total, 100 * gate_act / total, 100 * vad_not / total)
)
print("max_inactive_gap=%.2fs (need 1.0s for end_silence)" % (max_sil * 0.03))
if rms_vad:
    print(
        "rms when vad=true: p10=%.0f p50=%.0f p90=%.0f  gate=%d hangover=%.0f"
        % (
            statistics.quantiles(rms_vad, n=10)[0],
            statistics.median(rms_vad),
            statistics.quantiles(rms_vad, n=10)[8],
            gate,
            gate * float(os.environ.get("START_RATIO", "0.5")),
        )
    )

print("\nthreshold sweep (hangover=1.0):")
for thr in [800, 1000, 1119, 1400, 1800, 2500, 3500, 5000]:
    max_s = cur = act = 0
    n = 0
    for off in range(0, len(seg) - fb + 1, fb):
        frame = amplify_pcm_int16(seg[off : off + fb], gain)
        n += 1
        if is_active_speech_frame(vad, frame, sr, thr, True, 1.0):
            act += 1
            cur = 0
        else:
            cur += 1
            max_s = max(max_s, cur)
    print("  rms>=%4d: max_gap=%.2fs active=%.1f%%" % (thr, max_s * 0.03, 100 * act / n))
