#!/usr/bin/env bash
# 一边与 PERCY 轮流对话，一边 stamp 对齐录制头相机 + 外置 Rode（同 session 目录）
#
# 用法:
#   配置 ~/Research/.env.local（见 .env.local.example）
#   ./record_dialogue_session.sh 13
#
# 产出目录: $PERCY_DATA_DIR/<session_id>/
#   - 问卷: pre_survey.json, profile.json, post_survey.json（见 run_pre_survey.sh / run_post_survey.sh）
#   - 录制: audio.wav, whole_video.mp4, recording_meta.json, finalize.done
#   - 对话: chat_history.json, dialogue_timeline.json, utterances/user_*.wav
#   - 可选: benchmark_manifest.json（脚本结束自动跑）
#
# 结束: Ctrl+C 一次 → 停止录制并 wait_finalize
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${1:?用法: $0 <session_id>  例: $0 13}"
shift
WAIT_SH="$ROOT/percy_ws/src/percy/scripts/wait_finalize.sh"

if [[ -f "$ROOT/.env.local" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env.local"
  set +a
fi

# shellcheck source=/dev/null
source "$ROOT/research_paths.sh"
normalize_percy_data_dir "$ROOT"
OUT_DIR="$PERCY_DATA_DIR/$SESSION"
mkdir -p "$PERCY_DATA_DIR"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "请配置 $ROOT/.env.local（复制自 .env.local.example）" >&2
  exit 1
fi

if [[ -f "$ROOT/docker_ros1_noetic/env_ari.sh" ]] && { [[ -f /.dockerenv ]] || [[ -f /opt/ros/noetic/setup.bash ]]; }; then
  # shellcheck source=/dev/null
  source "$ROOT/docker_ros1_noetic/env_ari.sh" 2>/dev/null || true
fi
# 先 PERCY 再 percy_ws：后者必须在 overlay 顶层，否则 roslaunch 找不到 percy / percy_dialogue
if [[ -f "$ROOT/PERCY/devel/setup.bash" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/PERCY/devel/setup.bash"
fi
if [[ -f "$ROOT/percy_ws/devel/setup.bash" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/percy_ws/devel/setup.bash"
fi
# 链入 PERCY devel（emotion_model 节点）；勿仅 prepend src 以免 roslaunch 找不到 streamdata.py
if [[ -f "$ROOT/PERCY/devel/setup.bash" ]]; then
  export CMAKE_PREFIX_PATH="${CMAKE_PREFIX_PATH:-$ROOT/percy_ws/devel:$ROOT/PERCY/devel:/opt/ros/noetic}"
elif [[ -d "$ROOT/PERCY/src/emotion_model" ]]; then
  export ROS_PACKAGE_PATH="${ROS_PACKAGE_PATH:-}:$ROOT/PERCY/src"
  export ROS_PACKAGE_PATH="${ROS_PACKAGE_PATH#:}"
  export CMAKE_PREFIX_PATH="${CMAKE_PREFIX_PATH:-$ROOT/percy_ws/devel:/opt/ros/noetic}"
fi

LIVE_NODE="$ROOT/percy_ws/devel/lib/percy_dialogue/live_dialogue.py"
LIVE_LAUNCH="$ROOT/percy_ws/src/percy_dialogue/launch/live_session.launch"
if [[ -f "$ROOT/percy_ws/devel/share/percy_dialogue/launch/live_session.launch" ]]; then
  LIVE_LAUNCH="$ROOT/percy_ws/devel/share/percy_dialogue/launch/live_session.launch"
fi
if [[ ! -x "$LIVE_NODE" && ! -f "$LIVE_NODE" ]]; then
  echo "未找到 live_dialogue（需先编译）:" >&2
  echo "  cd $ROOT/percy_ws && catkin_make && source devel/setup.bash" >&2
  exit 1
fi
if [[ ! -f "$LIVE_LAUNCH" ]]; then
  echo "未找到 live_session.launch: $LIVE_LAUNCH" >&2
  exit 1
fi

EMOTION_ARGS=()
if [[ "${PERCY_SKIP_EMOTION_MODEL:-0}" == "1" ]]; then
  EMOTION_ARGS=(enable_emotion_model:=false)
  echo "    视觉 FER: 已关闭 (PERCY_SKIP_EMOTION_MODEL=1)"
elif command -v rospack >/dev/null 2>&1 && rospack find emotion_model >/dev/null 2>&1; then
  if python3 -c "import basetrainer" 2>/dev/null; then
    echo "    视觉 FER: emotion_model/streamdata.py (CPU)"
  else
    echo "    视觉 FER: 依赖未装，本次仅 VADER。容器内:"
    echo "      bash /workspace/docker_ros1_noetic/install_emotion_model_deps.sh"
    EMOTION_ARGS=(enable_emotion_model:=false)
  fi
else
  EMOTION_ARGS=(enable_emotion_model:=false)
  echo "    视觉 FER: 未启用（仅 VADER）。编译 PERCY 后重试:"
  echo "      cd $ROOT/PERCY && catkin_make && source devel/setup.bash"
  echo "      bash $ROOT/docker_ros1_noetic/install_emotion_model_deps.sh"
fi

echo "=== 对话 + 对齐录制 session=$SESSION ==="
echo "    目录: $OUT_DIR"
if [[ ! -f "$OUT_DIR/profile.json" ]]; then
  echo "    提示: 尚无 profile.json — 对话前可先运行: ./run_pre_survey.sh $SESSION"
else
  echo "    profile: $OUT_DIR/profile.json (persona prompt 已就绪)"
fi
echo "    包: percy_dialogue live_session.launch (对话 + A/V + 可选 FER)"
echo "    结束: Ctrl+C"
echo "    对话后可填反馈: ./run_post_survey.sh $SESSION"
echo ""
echo "提示: 外置麦需 ./ros1_ari.sh；音量: ./set_robot_volume.sh"
echo "      说完请停顿 ~1s，等终端 End silence / You said: 再听机器人回复"
echo "      端点检测: 默认 Silero VAD（无 silero 时: bash docker_ros1_noetic/install_silero_vad.sh）"
echo "      不想等静音: 另开终端 rosservice call /percy_live/end_turn \"{}\""
echo "      自检: bash $ROOT/check_percy_affect_ready.sh"
echo ""

export PERCY_DATA_DIR
roslaunch "$LIVE_LAUNCH" "session_id:=${SESSION}" "${EMOTION_ARGS[@]}" "$@"

if [[ -f "$OUT_DIR/recording_meta.json" && -x "$WAIT_SH" ]]; then
  echo ""
  echo "=== 等待视频 finalize ==="
  bash "$WAIT_SH" "$OUT_DIR" || true
fi

if command -v rosrun >/dev/null 2>&1; then
  rosrun percy_dialogue build_benchmark_manifest.py "$OUT_DIR" || true
fi
