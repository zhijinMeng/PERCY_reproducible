#!/usr/bin/env bash
# 简短轮流对话（onboard 麦）
# 用法: ./run_turn_dialogue.sh [session_id]
set -euo pipefail

SESSION_ID="${1:-dialogue01}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$ROOT/.env.local" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env.local"
  set +a
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "请配置 $ROOT/.env.local（复制自 .env.local.example）" >&2
  exit 1
fi

export PERCY_DATA_DIR="${PERCY_DATA_DIR:-$ROOT/percy_data}"
export ARI_ROS_IP="${ARI_ROS_IP:-10.68.0.130}"
export ARI_ROS_USE_LOOPBACK="${ARI_ROS_USE_LOOPBACK:-0}"

echo "PERCY 轮流对话 session=$SESSION_ID"
echo "  数据目录: $PERCY_DATA_DIR/$SESSION_ID"
echo "  包: percy_dialogue/turn_dialogue.launch"
echo ""

cd "$ROOT"
exec ./ros1_ari.sh bash -lc "
  source /opt/ros/noetic/setup.bash
  source /workspace/docker_ros1_noetic/env_ari.sh
  python3 -c 'import openai, webrtcvad; assert openai.__version__.startswith(\"1.\")' 2>/dev/null || bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh
  python3 -c 'from pal_interaction_msgs.msg import TtsAction' 2>/dev/null || bash /workspace/docker_ros1_noetic/install_pal_msgs.sh
  source /workspace/percy_ws/devel/setup.bash
  export PERCY_DATA_DIR=$PERCY_DATA_DIR
  roslaunch percy_dialogue turn_dialogue.launch session_id:=$SESSION_ID
"
