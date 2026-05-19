#!/usr/bin/env bash
# 容器内缺少 arecord 时安装 alsa-utils（临时）；持久化请宿主机 ./ros1_ari.sh --rebuild
set -euo pipefail
if command -v arecord >/dev/null 2>&1; then
  echo "OK: arecord 已存在: $(command -v arecord)"
  arecord -l 2>/dev/null | head -8 || true
  exit 0
fi
echo "安装 alsa-utils …"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends alsa-utils
command -v arecord
arecord -l | head -12
