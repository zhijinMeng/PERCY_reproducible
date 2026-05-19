#!/usr/bin/env bash
# 一边与 PERCY 轮流对话，一边 stamp 对齐录制头相机 + 外置 Rode（同 session 目录）
#
# 用法:
#   配置 ~/Research/.env.local（见 .env.local.example）
#   ./record_dialogue_session.sh 13
#
# 产出目录: $PERCY_DATA_DIR/<session_id>/
#   - 录制: audio.wav, whole_video.mp4, recording_meta.json, finalize.done
#   - 对话: chat_history.json, dialogue_timeline.json, utterances/user_*.wav
#   - 可选: benchmark_manifest.json（脚本结束自动跑）
#
# 结束: Ctrl+C 一次 → 停止录制并 wait_finalize
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${1:?用法: $0 <session_id>  例: $0 13}"
shift

export PERCY_DATA_DIR="${PERCY_DATA_DIR:-$ROOT/percy_data}"
OUT_DIR="$PERCY_DATA_DIR/$SESSION"
WAIT_SH="$ROOT/percy_ws/src/percy/scripts/wait_finalize.sh"

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

mkdir -p "$PERCY_DATA_DIR"

if [[ -f "$ROOT/docker_ros1_noetic/env_ari.sh" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/docker_ros1_noetic/env_ari.sh"
fi
if [[ -f "$ROOT/percy_ws/devel/setup.bash" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/percy_ws/devel/setup.bash"
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

echo "=== 对话 + 对齐录制 session=$SESSION ==="
echo "    目录: $OUT_DIR"
echo "    包: percy_dialogue live_session.launch (实时对话 + 对齐录制)"
echo "    结束: Ctrl+C"
echo ""
echo "提示: 外置麦需 ./ros1_ari.sh（自动 --audio）；机器人喇叭见 experience/PERCY轮流对话启动说明.md §5"
echo ""

export PERCY_DATA_DIR
roslaunch "$LIVE_LAUNCH" "session_id:=${SESSION}" "$@"

if [[ -f "$OUT_DIR/recording_meta.json" && -x "$WAIT_SH" ]]; then
  echo ""
  echo "=== 等待视频 finalize ==="
  bash "$WAIT_SH" "$OUT_DIR" || true
fi

if command -v rosrun >/dev/null 2>&1; then
  rosrun percy_dialogue build_benchmark_manifest.py "$OUT_DIR" || true
fi
