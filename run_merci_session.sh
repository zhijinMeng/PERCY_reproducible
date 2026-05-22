#!/usr/bin/env bash
# MERCI 完整采集编排：事前问卷 → 对话+录制 → 事后反馈
#
# 用法:
#   ./run_merci_session.sh <session_id> [record_dialogue_session.sh 额外参数...]
#
# 示例:
#   ./run_merci_session.sh 27
#   ./run_merci_session.sh 27 audio_gain:=1.2 end_silence_sec:=1.0 vad_mode:=2
#
# 选项（放在 session_id 之后、roslaunch 参数之前）:
#   --skip-pre       跳过事前问卷
#   --skip-post      跳过事后问卷
#   --force-pre      重新填事前问卷
#   --run-dialogue   在本环境直接跑对话（仅 Docker 内推荐；宿主机勿用）
#
# 默认流程（宿主机）:
#   1. 事前问卷（浏览器自动打开，Submit 后继续）
#   2. 提示在 Docker 里跑对话；你 Ctrl+C 结束对话后回到本终端按 Enter
#   3. 事后问卷（浏览器自动打开）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION=""
SKIP_PRE=0
SKIP_POST=0
FORCE_PRE=0
RUN_DIALOGUE=0
RECORD_ARGS=()

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --skip-pre) SKIP_PRE=1; shift ;;
    --skip-post) SKIP_POST=1; shift ;;
    --force-pre) FORCE_PRE=1; shift ;;
    --run-dialogue) RUN_DIALOGUE=1; shift ;;
    *)
      if [[ -z "$SESSION" ]]; then
        SESSION="$1"
        shift
      else
        RECORD_ARGS+=("$1")
        shift
      fi
      ;;
  esac
done

[[ -n "$SESSION" ]] || usage 1

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

ensure_data_dir_writable() {
  local probe="$PERCY_DATA_DIR/.write_probe_$$"
  if mkdir -p "$PERCY_DATA_DIR" 2>/dev/null && touch "$probe" 2>/dev/null; then
    rm -f "$probe"
    return 0
  fi
  echo "错误: 无法在 PERCY_DATA_DIR 写入: $PERCY_DATA_DIR" >&2
  echo "  常见原因: 目录由 Docker 创建，属主为 nobody/root，宿主机用户无写权限。" >&2
  echo "  修复（本机执行一次）:" >&2
  echo "    sudo chown -R \"\$(whoami):\$(whoami)\" \"$PERCY_DATA_DIR\"" >&2
  echo "  或改用可写目录:" >&2
  echo "    export PERCY_DATA_DIR=\"\$HOME/percy_data\"" >&2
  exit 1
}

ensure_data_dir_writable
SURVEY_PY="$ROOT/percy_surveys/survey_server.py"
RECORD_SH="$ROOT/record_dialogue_session.sh"
SURVEY_HOST="${PERCY_SURVEY_HOST:-127.0.0.1}"
SURVEY_PORT="${PERCY_SURVEY_PORT:-8765}"
SERVER_PID=""

cleanup_server() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  SERVER_PID=""
}
trap cleanup_server EXIT INT TERM

wait_for_survey_file() {
  local target="$1"
  local label="$2"
  local url="$3"
  echo ""
  echo ">>> $label"
  echo "    浏览器打开: $url"
  echo "    填完点 Submit，脚本检测到文件后自动继续（最多等 60 分钟）"
  echo ""

  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi

  local deadline=$((SECONDS + 3600))
  while [[ ! -f "$target" ]]; do
    if [[ $SECONDS -ge $deadline ]]; then
      echo "超时：未生成 $target" >&2
      exit 1
    fi
    if [[ -n "$SERVER_PID" ]] && ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "问卷 server 已退出，但未生成 $target" >&2
      exit 1
    fi
    sleep 1
  done
  echo "    已保存: $target"
  cleanup_server
}

start_survey() {
  local mode="$1"
  cleanup_server
  python3 "$SURVEY_PY" \
    --host "$SURVEY_HOST" \
    --port "$SURVEY_PORT" \
    --session "$SESSION" \
    --mode "$mode" \
    --no-open &
  SERVER_PID=$!
  sleep 0.8
}

in_docker() {
  [[ -f /.dockerenv ]]
}

can_run_dialogue_here() {
  in_docker && command -v roslaunch >/dev/null 2>&1 \
    && rospack find percy_dialogue >/dev/null 2>&1
}

wait_dialogue_done() {
  local args_str="${RECORD_ARGS[*]:-}"
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "║  [2/3] 请在 Docker 里跑对话（勿在本终端 Ctrl+C 整个脚本）      ║"
  echo "╚══════════════════════════════════════════════════════════════╝"
  echo ""
  echo "  另开一个终端："
  echo "    cd ~/Research && ./ros1_ari.sh"
  echo "  容器内："
  echo "    source /workspace/docker_ros1_noetic/env_ari.sh"
  if [[ -n "$args_str" ]]; then
    echo "    ./record_dialogue_session.sh $SESSION $args_str"
  else
    echo "    ./record_dialogue_session.sh $SESSION audio_gain:=1.2 end_silence_sec:=1.0 vad_mode:=2"
  fi
  echo ""
  echo "  对话在容器里 Ctrl+C 结束 → 回到【本终端】按 Enter → 打开事后问卷"
  echo ""
  if [[ -f "$OUT_DIR/chat_history.json" ]]; then
    echo "  （已检测到 chat_history.json）"
  fi
  read -r -p ">>> 对话已完成？按 Enter 继续事后问卷… " _
}

mkdir -p "$OUT_DIR"

echo "=== MERCI session $SESSION ==="
echo "    目录: $OUT_DIR"
echo ""

# --- 1. Pre-session profile ---
need_pre=1
if [[ "$SKIP_PRE" == "1" ]]; then
  need_pre=0
  echo "[1/3] 跳过事前问卷 (--skip-pre)"
elif [[ -f "$OUT_DIR/profile.json" && "$FORCE_PRE" != "1" ]]; then
  need_pre=0
  echo "[1/3] 已有 profile.json，跳过事前问卷（重填请加 --force-pre）"
fi

if [[ "$need_pre" == "1" ]]; then
  start_survey pre
  wait_for_survey_file \
    "$OUT_DIR/profile.json" \
    "事前问卷（profile）" \
    "http://${SURVEY_HOST}:${SURVEY_PORT}/pre?session=${SESSION}"
fi

# --- 2. Dialogue + recording ---
echo ""
if [[ "$RUN_DIALOGUE" == "1" ]] || can_run_dialogue_here; then
  echo "[2/3] 对话 + 对齐录制（本环境，结束后 Ctrl+C）"
  echo "    调用: $RECORD_SH $SESSION ${RECORD_ARGS[*]:-}"
  echo ""
  bash "$RECORD_SH" "$SESSION" "${RECORD_ARGS[@]}"
else
  wait_dialogue_done
fi

# --- 3. Post-session feedback ---
if [[ "$SKIP_POST" == "1" ]]; then
  echo ""
  echo "[3/3] 跳过事后问卷 (--skip-post)"
else
  if [[ -f "$OUT_DIR/post_survey.json" ]]; then
    echo ""
    echo "[3/3] 已有 post_survey.json，跳过事后问卷"
  else
    echo ""
    echo "[3/3] 事后反馈问卷（对话结束后）"
    start_survey post
    wait_for_survey_file \
      "$OUT_DIR/post_survey.json" \
      "事后反馈问卷" \
      "http://${SURVEY_HOST}:${SURVEY_PORT}/post?session=${SESSION}"
  fi
fi

echo ""
echo "=== MERCI session $SESSION 完成 ==="
echo "    pre:    ${OUT_DIR}/pre_survey.json"
echo "    profile:${OUT_DIR}/profile.json"
echo "    dialogue:${OUT_DIR}/chat_history.json"
echo "    av:     ${OUT_DIR}/audio.wav  ${OUT_DIR}/whole_video.mp4"
echo "    post:   ${OUT_DIR}/post_survey.json"
echo ""
