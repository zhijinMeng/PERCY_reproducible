#!/usr/bin/env bash
# Silero VAD for live_dialogue（白天风扇环境优于 WebRTC VAD）
#
# 容器内: bash /workspace/docker_ros1_noetic/install_silero_vad.sh
set -euo pipefail
pip3 install --no-cache-dir "silero-vad>=5.0" "torchaudio>=2.1,<2.2"
python3 - <<'PY'
from silero_vad import VADIterator, load_silero_vad
import torch

m = load_silero_vad()
it = VADIterator(m, sampling_rate=16000, min_silence_duration_ms=1000)
x = torch.zeros(512)
it(x, return_seconds=False)
it.reset_states()
print("ok: silero-vad + VADIterator")
PY
