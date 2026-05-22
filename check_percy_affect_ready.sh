#!/usr/bin/env bash
# 检查「对话 + VADER + 笔记本视觉 FER」是否就绪（容器内运行）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail() { echo "[FAIL] $*" >&2; exit 1; }
warn() { echo "[WARN] $*"; }
ok() { echo "[OK]   $*"; }

source /opt/ros/noetic/setup.bash 2>/dev/null || true
[[ -f "$ROOT/PERCY/devel/setup.bash" ]] && source "$ROOT/PERCY/devel/setup.bash"
[[ -f "$ROOT/percy_ws/devel/setup.bash" ]] && source "$ROOT/percy_ws/devel/setup.bash"
if [[ -d "$ROOT/PERCY/src/emotion_model" ]]; then
  export ROS_PACKAGE_PATH="$ROOT/PERCY/src:${ROS_PACKAGE_PATH}"
  export CMAKE_PREFIX_PATH="$ROOT/percy_ws/devel:$ROOT/PERCY/devel:/opt/ros/noetic"
fi
[[ -f "$ROOT/docker_ros1_noetic/env_ari.sh" ]] && source "$ROOT/docker_ros1_noetic/env_ari.sh"

rospack find percy_dialogue >/dev/null || fail "percy_dialogue 未编译"
rospack find percy >/dev/null || fail "percy 未编译"
ok "percy_ws 包"

python3 -c "import webrtcvad, openai; from nltk.sentiment.vader import SentimentIntensityAnalyzer; SentimentIntensityAnalyzer()" \
  || fail "对话依赖缺失: install_dialogue_deps.sh"

if rospack find emotion_model >/dev/null 2>&1; then
  ok "emotion_model 已 catkin 安装"
else
  warn "emotion_model 未找到 → 运行: cd /workspace/PERCY && catkin_make && source devel/setup.bash"
fi

python3 - <<'PY' || warn "FER 依赖 → bash docker_ros1_noetic/install_emotion_model_deps.sh"
import cv2, torch, requests
from basetrainer.utils import setup_config
print("FER CPU deps ok: torch", torch.__version__, "cv2", cv2.__version__)
PY

if [[ -f "$ROOT/PERCY/src/emotion_model/data/pretrained/mobilenet_v2_1.0_CrossEntropyLoss_20230313090258/model/latest_model_099_94.7200.pth" ]]; then
  ok "FER 权重文件存在"
else
  warn "缺少 latest_model_099_94.7200.pth"
fi

if [[ -n "${OPENAI_API_KEY:-}" ]]; then ok "OPENAI_API_KEY 已设置"; else warn "OPENAI_API_KEY 未设置"; fi

echo ""
echo "启动完整系统:"
echo "  bash /workspace/record_dialogue_session.sh <session_id>"
