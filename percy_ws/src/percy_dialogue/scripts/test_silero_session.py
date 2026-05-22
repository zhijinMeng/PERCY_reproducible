#!/usr/bin/env python3
import wave

import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad

path = "/workspace/percy_data/29/audio.wav"
with wave.open(path) as w:
    pcm = w.readframes(w.getnframes())

samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
model = load_silero_vad()
it = VADIterator(
    model,
    threshold=0.5,
    sampling_rate=16000,
    min_silence_duration_ms=1000,
    speech_pad_ms=100,
)
starts = ends = 0
for i in range(0, len(samples) - 512, 512):
    chunk = torch.from_numpy(samples[i : i + 512])
    r = it(chunk, return_seconds=False)
    if r and "start" in r:
        starts += 1
        print("start", r, "at sample", i)
    if r and "end" in r:
        ends += 1
        print("end", r, "at sample", i)
print("total starts=%d ends=%d" % (starts, ends))
