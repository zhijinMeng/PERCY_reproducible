#!/usr/bin/env bash
# Run offline FER export inside the PERCY ROS1 Docker image (CPU).
set -euo pipefail
ROOT="${HOME}/Research"
IMAGE="${ROS1_DOCKER_IMAGE:-research/ros1-noetic-percy:local}"
SCRIPT="/workspace/paper_writing/Paper_writing/Claude_Writing/analysis/run_offline_fer_probs.py"
EXTRA_ARGS=("$@")

docker run --rm \
  -v "${ROOT}:/workspace" \
  -w /workspace/PERCY/src/emotion_model \
  "${IMAGE}" \
  bash -lc "
    if ! python3 -c 'import torch, cv2' 2>/dev/null; then
      bash /workspace/docker_ros1_noetic/install_emotion_model_deps.sh
    fi
    python3 ${SCRIPT} ${EXTRA_ARGS[*]:-}
  "
