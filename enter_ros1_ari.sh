#!/usr/bin/env bash
# 兼容入口：与 ./ros1_ari.sh 相同
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ros1_ari.sh" "$@"
