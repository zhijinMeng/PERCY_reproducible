#!/usr/bin/env bash
# 在 Docker 内（已 source percy_ws）快速自检 percy + percy_dialogue
# 用法: bash /workspace/test_percy_ws.sh
#       bash /workspace/test_percy_ws.sh --live   # 需连机器人，测 topic + 可选 TTS
set -euo pipefail

LIVE=0
[[ "${1:-}" == "--live" ]] && LIVE=1

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "OK: $*"; }

source /opt/ros/noetic/setup.bash
[[ -f /workspace/percy_ws/devel/setup.bash ]] || fail "先 catkin_make: cd /workspace/percy_ws && catkin_make"
source /workspace/percy_ws/devel/setup.bash

echo "=== 1. 包与 launch ==="
rospack find percy >/dev/null || fail "percy"
rospack find percy_dialogue >/dev/null || fail "percy_dialogue"
[[ -f "$(rospack find percy)/launch/record_aligned.launch" ]] || fail "percy record_aligned.launch"
[[ -f "$(rospack find percy_dialogue)/launch/live_session.launch" ]] || fail "live_session.launch"
ok "rospack + launch 文件"

echo "=== 2. Python 依赖 ==="
python3 -c "from pal_interaction_msgs.msg import TtsAction; print('  pal_interaction_msgs')"
python3 -c "import webrtcvad, openai; from nltk.sentiment.vader import SentimentIntensityAnalyzer; assert openai.__version__.startswith('1.'); SentimentIntensityAnalyzer(); print('  openai', openai.__version__, '+ webrtcvad + VADER')" \
  || fail "运行: bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh"

echo "=== 3. 已安装节点（仅检查文件，不启动）==="
check_rosrun() {
  local pkg=$1 node=$2
  local p
  p="$(rosrun "$pkg" "$node" 2>&1 | head -1)" || true
  if [[ -x "/workspace/percy_ws/devel/lib/${pkg}/${node}" ]]; then
    echo "  ${pkg}/${node}"
    return 0
  fi
  fail "缺少 devel/lib/${pkg}/${node}"
}
check_rosrun percy stamp_aligned_recorder.py
check_rosrun percy_dialogue live_dialogue.py
check_rosrun percy_dialogue tts_test.py
check_rosrun percy_dialogue build_benchmark_manifest.py
ok "节点已 catkin 安装"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "WARN: OPENAI_API_KEY 未设置（对话测试需要）"
else
  ok "OPENAI_API_KEY 已设置"
fi

if [[ "$LIVE" -eq 0 ]]; then
  echo ""
  echo "静态检查完成。连机器人后运行:"
  echo "  bash /workspace/test_percy_ws.sh --live"
  exit 0
fi

echo "=== 4. 机器人 topic（约 5s）==="
[[ -f /workspace/docker_ros1_noetic/env_ari.sh ]] && source /workspace/docker_ros1_noetic/env_ari.sh
export ARI_ROS_USE_LOOPBACK="${ARI_ROS_USE_LOOPBACK:-0}"

timeout 6 rostopic hz /audio/channel0 -w 3 2>&1 | tail -3 || echo "WARN: /audio/channel0 无数据"
timeout 6 rostopic hz /head_front_camera/color/image_raw -w 3 2>&1 | tail -3 || echo "WARN: 头相机无数据"

echo "=== 5. /tts（可选）==="
trap 'stty echo 2>/dev/null || true' EXIT INT TERM
read -r -p "发送一句 TTS 测试? [y/N] " ans
trap - EXIT INT TERM
if [[ "${ans,,}" == "y" ]]; then
  rosrun percy_dialogue tts_test.py "PERCY workspace test."
  ok "TTS 完成（请确认是否听到）"
fi

echo ""
echo "完整联调:"
echo "  rosrun percy_dialogue tts_test.py \"Hello\""
echo "  bash /workspace/record_dialogue_session.sh test01"
echo "  /workspace/record_dialogue_session.sh 14"
