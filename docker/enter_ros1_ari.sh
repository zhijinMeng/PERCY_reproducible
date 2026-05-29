#!/usr/bin/env bash
# 兼容入口：与仓库根目录 ./ros1_ari.sh 相同
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../ros1_ari.sh" "$@"
