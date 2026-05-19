#!/usr/bin/env bash
# 在 PERCY 工作区加入 PAL 消息包（供 /tts 等 action client 使用）
# 来源: https://github.com/pal-robotics/pal_msgs/tree/indigo-devel
set -euo pipefail

# 默认 percy_ws；旧 PERCY 工作区: install_pal_msgs.sh /workspace/PERCY/src
WS_SRC="${1:-/workspace/percy_ws/src}"
PAL_MSGS_DIR="$WS_SRC/pal_msgs"
BRANCH="${PAL_MSGS_BRANCH:-indigo-devel}"

if [[ -d "$PAL_MSGS_DIR/.git" ]]; then
  echo "pal_msgs 已存在: $PAL_MSGS_DIR"
else
  echo "克隆 pal_msgs ($BRANCH) ..."
  git clone --depth 1 -b "$BRANCH" https://github.com/pal-robotics/pal_msgs.git "$PAL_MSGS_DIR"
fi

# 只编 TTS 所需包；其余子包会拉 humanoid_nav_msgs 等额外依赖
for d in "$PAL_MSGS_DIR"/*/; do
  [[ "$d" == *pal_interaction_msgs/ ]] && continue
  touch "${d}CATKIN_IGNORE"
done

WS_ROOT="$(cd "$(dirname "$WS_SRC")" && pwd)"
echo "编译 pal_interaction_msgs @ $WS_ROOT ..."
cd "$WS_ROOT"
source /opt/ros/noetic/setup.bash
catkin_make --pkg pal_interaction_msgs pal_common_msgs 2>/dev/null || catkin_make
source devel/setup.bash
python3 -c "from pal_interaction_msgs.msg import TtsAction, TtsGoal, TtsFeedback; print('ok: pal_interaction_msgs')"
