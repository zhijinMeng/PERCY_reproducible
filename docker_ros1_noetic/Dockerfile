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
    && python3 -c "import openai, webrtcvad; print('image deps ok: openai', openai.__version__)"
