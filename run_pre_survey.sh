#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="${1:?用法: $0 <session_id>}"
shift
export PERCY_DATA_DIR="${PERCY_DATA_DIR:-$ROOT/percy_data}"
exec python3 "$ROOT/percy_surveys/survey_server.py" --session "$SESSION" --mode pre "$@"
