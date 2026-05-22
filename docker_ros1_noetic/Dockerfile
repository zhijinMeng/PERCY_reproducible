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
print("image deps ok: openai", openai.__version__, "+ VADER")
PY

# 视觉 FER（streamdata.py，CPU 内推理）
RUN python3 -m pip install --no-cache-dir --upgrade "pip<25" setuptools wheel \
    && python3 -m pip install --no-cache-dir --force-reinstall \
        torch==2.1.2 torchvision==0.16.2 \
        --index-url https://download.pytorch.org/whl/cpu --no-deps \
    && python3 -m pip install --no-cache-dir \
        filelock sympy networkx jinja2 fsspec typing-extensions==4.12.2 \
        "numpy>=1.21,<1.24" pillow requests \
        "opencv-python-headless>=4.5,<4.6" easydict tqdm \
        pybaseutils==0.7.6 basetrainer \
    && python3 -c "import cv2, torch; from basetrainer.utils import setup_config; print('FER cpu ok', torch.__version__, cv2.__version__)"
