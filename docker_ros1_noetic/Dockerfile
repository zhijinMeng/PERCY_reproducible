# ROS1 Noetic + 依赖（percy_ws / percy_dialogue）
FROM osrf/ros:noetic-desktop-full

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-noetic-audio-common-msgs \
        ffmpeg \
        alsa-utils \
        python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir \
        "openai==1.14.1" \
        "webrtcvad==2.0.10" \
        "httpx<0.28" \
        "nltk>=3.6" \
    && python3 - <<'PY'
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
nltk.download("vader_lexicon", quiet=True)
SentimentIntensityAnalyzer()
import openai, webrtcvad
print("image deps ok: openai", openai.__version__)
PY
