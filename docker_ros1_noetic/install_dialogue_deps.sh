#!/usr/bin/env bash
# live_dialogue Python 依赖（openai / silero-vad / webrtcvad / nltk+VADER）
#
# 若镜像已用最新 Dockerfile 构建（./ros1_ari.sh --rebuild），新容器自带依赖，无需再跑本脚本。
# 仅在使用旧镜像、或 pip 被删改时，在容器内补装：
#   bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh
set -euo pipefail
apt-get update
apt-get install -y --no-install-recommends python3-pip
# openai 2.x 需 jiter>=0.10，Ubuntu 20.04 / Python 3.8 下 pip 装不上；与 PERCY 一致用 1.14.x
pip3 install --no-cache-dir \
  "openai==1.14.1" "webrtcvad==2.0.10" "httpx<0.28" "nltk>=3.6" \
  "silero-vad>=5.0" "torchaudio>=2.1,<2.2"
python3 - <<'PY'
import nltk
import openai
import webrtcvad
import torch
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from silero_vad import VADIterator, load_silero_vad
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon", quiet=True)
SentimentIntensityAnalyzer()
m = load_silero_vad()
VADIterator(m, sampling_rate=16000)(torch.zeros(512), return_seconds=False)
print("ok: openai", openai.__version__, "+ silero-vad + webrtcvad + VADER")
PY
