# ROS1 Noetic + 依赖（percy_ws 需要 audio_common_msgs）
FROM osrf/ros:noetic-desktop-full

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ros-noetic-audio-common-msgs \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*
