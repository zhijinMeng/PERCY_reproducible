#!/usr/bin/env python3
"""
Offline replay of live_dialogue WebRTC VAD end-of-utterance logic.

Usage:
  python3 test_vad_eou.py /path/to.wav
  python3 test_vad_eou.py --max-utterance 20 --end-silence 0.8 file.wav

Prints per-frame speech/silence timeline and which path ended the utterance.
"""
from __future__ import print_function

import argparse
import struct
import sys
import wave

import webrtcvad


FRAME_MS = 30


def pcm_duration_sec(pcm, sample_rate):
    return float(len(pcm)) / float(2 * sample_rate)


def read_wav_pcm(path):
    with wave.open(path, "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
        if sample_width != 2:
            raise ValueError("need 16-bit PCM, got width=%d" % sample_width)
        pcm = wf.readframes(wf.getnframes())
    if channels == 2:
        mono = bytearray(len(pcm) // 2)
        for i in range(0, len(pcm) - 3, 4):
            struct.pack_into("<h", mono, i // 2, struct.unpack_from("<h", pcm, i)[0])
        pcm = bytes(mono)
    elif channels != 1:
        raise ValueError("need mono or stereo, got channels=%d" % channels)
    return pcm, sample_rate


def simulate_vad_eou(
    pcm,
    sample_rate,
    vad_mode=3,
    end_silence_sec=0.8,
    min_speech_sec=0.35,
    min_whisper_sec=0.5,
    max_utterance_sec=12.0,
    verbose=False,
):
    vad = webrtcvad.Vad(vad_mode)
    frame_bytes = int(sample_rate * FRAME_MS / 1000) * 2
    t0 = 0.0
    frame_dt = FRAME_MS / 1000.0

    speech_started = False
    speech_start_t = None
    last_speech_t = None
    utterance_pcm = bytearray()
    results = []

    offset = 0
    frame_idx = 0
    while offset + frame_bytes <= len(pcm):
        frame = pcm[offset : offset + frame_bytes]
        offset += frame_bytes
        now = t0 + frame_idx * frame_dt
        frame_idx += 1

        try:
            is_speech = vad.is_speech(frame, sample_rate)
        except Exception:
            continue

        if is_speech:
            if not speech_started:
                speech_started = True
                speech_start_t = now
                utterance_pcm = bytearray()
                if verbose:
                    print("  t=%.2fs speech_start" % now)
            last_speech_t = now
            utterance_pcm.extend(frame)
            duration = now - speech_start_t
            if duration >= max_utterance_sec:
                pcm_dur = pcm_duration_sec(bytes(utterance_pcm), sample_rate)
                results.append(
                    {
                        "reason": "max_utterance",
                        "end_t": now,
                        "duration_sec": pcm_dur,
                        "speech_span_sec": duration,
                    }
                )
                if verbose:
                    print(
                        "  t=%.2fs utterance_end reason=max_utterance dur=%.2fs"
                        % (now, pcm_dur)
                    )
                speech_started = False
                speech_start_t = None
                last_speech_t = None
                utterance_pcm = bytearray()
            continue

        if not speech_started:
            continue

        utterance_pcm.extend(frame)
        silence = now - last_speech_t
        duration = now - speech_start_t
        if silence >= end_silence_sec and duration >= min_speech_sec:
            pcm_dur = pcm_duration_sec(bytes(utterance_pcm), sample_rate)
            reason = "end_silence" if pcm_dur >= min_whisper_sec else "too_short"
            results.append(
                {
                    "reason": reason,
                    "end_t": now,
                    "duration_sec": pcm_dur,
                    "speech_span_sec": duration,
                    "trailing_silence_sec": silence,
                }
            )
            if verbose:
                print(
                    "  t=%.2fs utterance_end reason=%s dur=%.2fs silence=%.2fs"
                    % (now, reason, pcm_dur, silence)
                )
            speech_started = False
            speech_start_t = None
            last_speech_t = None
            utterance_pcm = bytearray()

    if speech_started:
        pcm_dur = pcm_duration_sec(bytes(utterance_pcm), sample_rate)
        results.append(
            {
                "reason": "eof_no_end",
                "end_t": t0 + frame_idx * frame_dt,
                "duration_sec": pcm_dur,
                "speech_span_sec": (last_speech_t or speech_start_t) - speech_start_t,
            }
        )

    return results


def speech_ratio_timeline(pcm, sample_rate, vad_mode=3, window_sec=0.5):
    vad = webrtcvad.Vad(vad_mode)
    frame_bytes = int(sample_rate * FRAME_MS / 1000) * 2
    frames_per_window = max(1, int(window_sec / (FRAME_MS / 1000.0)))
    windows = []
    speech_frames = 0
    total_frames = 0
    window_idx = 0
    offset = 0
    while offset + frame_bytes <= len(pcm):
        frame = pcm[offset : offset + frame_bytes]
        offset += frame_bytes
        try:
            if vad.is_speech(frame, sample_rate):
                speech_frames += 1
        except Exception:
            pass
        total_frames += 1
        if total_frames % frames_per_window == 0:
            t = window_idx * window_sec
            ratio = float(speech_frames) / frames_per_window
            windows.append((t, ratio))
            window_idx += 1
            speech_frames = 0
    return windows


def main():
    parser = argparse.ArgumentParser(description="Replay live_dialogue VAD EOU on wav")
    parser.add_argument("wav", nargs="+", help="16 kHz mono/stereo PCM wav")
    parser.add_argument("--vad-mode", type=int, default=3)
    parser.add_argument("--end-silence", type=float, default=0.8)
    parser.add_argument("--min-speech", type=float, default=0.35)
    parser.add_argument("--min-whisper", type=float, default=0.5)
    parser.add_argument("--max-utterance", type=float, default=12.0)
    parser.add_argument("--timeline", action="store_true", help="print 0.5s speech ratio")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    for path in args.wav:
        pcm, sr = read_wav_pcm(path)
        dur = pcm_duration_sec(pcm, sr)
        print("=== %s ===" % path)
        print(
            "  audio=%.2fs sr=%d  params: end_silence=%.1fs max_utterance=%.1fs vad_mode=%d"
            % (dur, sr, args.end_silence, args.max_utterance, args.vad_mode)
        )
        if args.timeline:
            print("  speech_ratio (0.5s windows, 1.0=all speech frames):")
            for t, ratio in speech_ratio_timeline(pcm, sr, args.vad_mode):
                bar = "#" * int(ratio * 20)
                print("    %5.1fs  %4.0f%%  %s" % (t, ratio * 100, bar))

        results = simulate_vad_eou(
            pcm,
            sr,
            vad_mode=args.vad_mode,
            end_silence_sec=args.end_silence,
            min_speech_sec=args.min_speech,
            min_whisper_sec=args.min_whisper,
            max_utterance_sec=args.max_utterance,
            verbose=args.verbose,
        )
        if not results:
            print("  (no utterance detected)")
            continue
        for i, r in enumerate(results, 1):
            extra = ""
            if "trailing_silence_sec" in r:
                extra = " trailing_silence=%.2fs" % r["trailing_silence_sec"]
            print(
                "  #%d end@%5.2fs reason=%-16s pcm_dur=%.2fs%s"
                % (i, r["end_t"], r["reason"], r["duration_sec"], extra)
            )
        reasons = [r["reason"] for r in results]
        print(
            "  summary: %d utterance(s)  end_silence=%d  max_utterance=%d  other=%d"
            % (
                len(results),
                sum(1 for x in reasons if x == "end_silence"),
                sum(1 for x in reasons if x == "max_utterance"),
                sum(1 for x in reasons if x not in ("end_silence", "max_utterance")),
            )
        )
        print("")


if __name__ == "__main__":
    main()
