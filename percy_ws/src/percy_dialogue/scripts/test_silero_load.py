#!/usr/bin/env python3
import sys

import numpy as np
import torch

print("loading silero...", flush=True)
model, utils = torch.hub.load(
    "snakers4/silero-vad", "silero_vad", trust_repo=True, onnx=True
)
VADIterator = utils[3]
it = VADIterator(
    model,
    threshold=0.5,
    sampling_rate=16000,
    min_silence_duration_ms=1000,
    speech_pad_ms=100,
)
z = torch.zeros(512)
print("silence:", it(z, return_seconds=False), flush=True)
it.reset_states()
for i in range(3):
    n = torch.randn(512) * 0.02
    r = it(n, return_seconds=False)
    if r:
        print("noise", i, r, flush=True)
print("done", flush=True)
