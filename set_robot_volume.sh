#!/usr/bin/env bash
# 设置 ARI 机器人机身喇叭音量（PulseAudio output0 + pal-default-sink）
# 用法:
#   ./set_robot_volume.sh          # 默认 60%
#   ./set_robot_volume.sh 45       # 指定百分比
set -euo pipefail

VOL="${1:-60}"
ROBOT_HOST="${ARI_ROBOT_SSH:-pal@10.68.0.1}"

if ! [[ "$VOL" =~ ^[0-9]+$ ]] || [[ "$VOL" -lt 0 ]] || [[ "$VOL" -gt 100 ]]; then
  echo "用法: $0 [0-100]   例: $0 60" >&2
  exit 1
fi

echo "设置 ${ROBOT_HOST} 喇叭音量为 ${VOL}% …"
ssh "$ROBOT_HOST" \
  "pactl set-default-sink output0; \
   pactl set-sink-mute output0 0; pactl set-sink-volume output0 ${VOL}%; \
   pactl set-sink-mute pal-default-sink 0; pactl set-sink-volume pal-default-sink ${VOL}%; \
   pactl list sinks | grep -E 'Name: (output0|pal-default-sink)|Volume:' | head -4"
echo "完成。"
