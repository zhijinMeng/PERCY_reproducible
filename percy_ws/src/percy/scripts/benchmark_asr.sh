#!/usr/bin/env bash
# 对已对齐的 session 跑本地 Whisper，导出 benchmark JSON
# 用法: benchmark_asr.sh /workspace/percy_data/10
set -euo pipefail
SESSION_DIR="${1:?session dir}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/benchmark_whisper_align.py" "$SESSION_DIR" "${@:2}"
