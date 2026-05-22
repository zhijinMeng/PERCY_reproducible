#!/usr/bin/env bash
# 宿主机 / 容器路径归一化（Research 根目录下的脚本 source）
#
#   source "$ROOT/research_paths.sh"
#   normalize_percy_data_dir "$ROOT"

normalize_percy_data_dir() {
  local root="${1:?research root directory}"
  if [[ ! -f /.dockerenv && "${PERCY_DATA_DIR:-}" == /workspace/* ]]; then
    export PERCY_DATA_DIR="$root/${PERCY_DATA_DIR#/workspace/}"
  fi
  export PERCY_DATA_DIR="${PERCY_DATA_DIR:-$root/percy_data}"
}
