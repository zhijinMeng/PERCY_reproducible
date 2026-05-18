#!/usr/bin/env bash
# 一键录制 + Ctrl+C 后自动等待 finalize（音画时长对齐）
# 宿主机或 Docker 内: ./record_aligned.sh <session_id> [roslaunch 额外参数...]
#
# 示例:
#   cd ~/Research && ./record_aligned.sh 10
#   PERCY_DATA_DIR=/workspace/percy_data ./record_aligned.sh 10
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${1:?用法: $0 <session_id>  例: $0 10}"
shift

export PERCY_DATA_DIR="${PERCY_DATA_DIR:-$ROOT/percy_data}"
OUT_DIR="$PERCY_DATA_DIR/$SESSION"
WAIT_SH="$ROOT/percy_ws/src/percy/scripts/wait_finalize.sh"

mkdir -p "$PERCY_DATA_DIR"

if [[ -f "$ROOT/docker_ros1_noetic/env_ari.sh" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/docker_ros1_noetic/env_ari.sh"
fi
if [[ -f "$ROOT/percy_ws/devel/setup.bash" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/percy_ws/devel/setup.bash"
fi

echo "=== 录制 session=$SESSION -> $OUT_DIR ==="
echo "    结束: Ctrl+C 一次，随后自动等待 finalize（长片可能要几分钟）"
echo ""

LAUNCH_EXIT=0
roslaunch percy record_aligned.launch "session_id:=${SESSION}" "$@" || LAUNCH_EXIT=$?

if [[ ! -f "$OUT_DIR/recording_meta.json" ]]; then
  echo "未生成 recording_meta.json，跳过 finalize 等待。"
  exit "$LAUNCH_EXIT"
fi

if [[ ! -x "$WAIT_SH" ]]; then
  echo "缺少 $WAIT_SH"
  exit 1
fi

echo ""
bash "$WAIT_SH" "$OUT_DIR"
WAIT_EXIT=$?

if [[ "$LAUNCH_EXIT" -ne 0 && "$WAIT_EXIT" -eq 0 ]]; then
  exit "$LAUNCH_EXIT"
fi
exit "$WAIT_EXIT"
