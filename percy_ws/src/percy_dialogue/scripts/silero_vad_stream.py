#!/usr/bin/env python3
"""Streaming Silero VAD for live_dialogue (16 kHz mono int16 PCM)."""
from __future__ import print_function

import numpy as np
import torch

# 16 kHz Silero chunk size (samples)
SILERO_CHUNK_SAMPLES = 512
SILERO_CHUNK_BYTES = SILERO_CHUNK_SAMPLES * 2


class SileroVadStream(object):
    """Feed int16 PCM bytes; yields 'start' / 'end' segment events."""

    def __init__(
        self,
        sample_rate=16000,
        threshold=0.5,
        min_silence_duration_ms=1000,
        speech_pad_ms=100,
    ):
        if sample_rate != 16000:
            raise ValueError("SileroVadStream only supports 16 kHz, got %d" % sample_rate)
        from silero_vad import VADIterator, load_silero_vad

        self._model = load_silero_vad()
        self._iterator = VADIterator(
            self._model,
            threshold=float(threshold),
            sampling_rate=sample_rate,
            min_silence_duration_ms=int(min_silence_duration_ms),
            speech_pad_ms=int(speech_pad_ms),
        )
        self._pending = bytearray()

    def reset_states(self):
        self._iterator.reset_states()
        self._pending = bytearray()

    def feed(self, pcm_int16_bytes):
        """Process amplified int16 PCM; return list of 'start' | 'end' events."""
        events = []
        if not pcm_int16_bytes:
            return events
        self._pending.extend(pcm_int16_bytes)
        while len(self._pending) >= SILERO_CHUNK_BYTES:
            chunk = bytes(self._pending[:SILERO_CHUNK_BYTES])
            del self._pending[:SILERO_CHUNK_BYTES]
            samples = torch.from_numpy(
                np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            )
            if samples.numel() != SILERO_CHUNK_SAMPLES:
                continue
            speech_dict = self._iterator(samples, return_seconds=False)
            if not speech_dict:
                continue
            if "start" in speech_dict:
                events.append("start")
            if "end" in speech_dict:
                events.append("end")
        return events
