#!/usr/bin/env bash
# Run offline FER export inside the PERCY ROS1 Docker image (CPU).
set -euo pipefail
ROOT="${RESEARCH_ROOT:-${HOME}/Research}"
IMAGE="${ROS1_DOCKER_IMAGE:-research/ros1-noetic-percy:local}"
SCRIPT="/workspace/paper_writing/Paper_writing/Claude_Writing/analysis/run_offline_fer_probs.py"
EXTRA_ARGS=("$@")

# Host path -> in-container path (symlinks under HF_Data/ often point outside /workspace).
NM_HOST="${NORMALIZED_MEDIA_ROOT:-${ROOT}/HF_Data/percy_data/normalized_media}"
NM_HOST="$(readlink -f "$NM_HOST")"
case "$NM_HOST" in
  "$ROOT"/*) NM_CONTAINER="/workspace${NM_HOST#"$ROOT"}" ;;
  *) echo "ERROR: NORMALIZED_MEDIA_ROOT must live under RESEARCH_ROOT=$ROOT (got $NM_HOST)" >&2; exit 1 ;;
esac
echo "FER data: host=$NM_HOST container=$NM_CONTAINER"

docker run --rm \
  -v "${ROOT}:/workspace" \
  -e "NORMALIZED_MEDIA_ROOT=${NM_CONTAINER}" \
  -w /workspace/PERCY/src/emotion_model \
  "${IMAGE}" \
  bash -lc "
    if ! python3 -c 'import torch, cv2' 2>/dev/null; then
      bash /workspace/docker_ros1_noetic/install_emotion_model_deps.sh
    fi
    python3 ${SCRIPT} ${EXTRA_ARGS[*]:-}
  "
