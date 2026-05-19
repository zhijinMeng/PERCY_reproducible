#!/usr/bin/env bash
# 仅测笔记本 USB 麦（不经 ROS）。在 Docker 内或宿主机均可。
#   bash /workspace/record_host_mic_only.sh mic_test01 10
set -euo pipefail

SESSION="${1:-mic_test01}"
DUR="${2:-10}"
ROOT="${PERCY_DATA_DIR:-/workspace/percy_data}"
if [[ "$ROOT" != /* ]]; then
  ROOT="/workspace/${ROOT#./}"
fi
OUT="${ROOT}/${SESSION}"
mkdir -p "$OUT"

# shellcheck source=docker_ros1_noetic/detect_host_usb_mic.sh
source "$(cd "$(dirname "$0")" && pwd)/docker_ros1_noetic/detect_host_usb_mic.sh"
DEV="$(percy_host_usb_mic_device || true)"
if [[ -z "$DEV" ]]; then
  echo "未检测到 USB 麦；宿主机 arecord -l 应见 NTUSB" >&2
  exit 1
fi

WAV="${OUT}/audio.wav"
echo "设备: $DEV"
echo "录制 ${DUR}s → ${WAV}"
echo "请对着 Rode 正常说话 …"

if ! command -v ffmpeg >/dev/null; then
  echo "需要 ffmpeg（Docker 镜像已含）" >&2
  exit 1
fi

ffmpeg -hide_banner -nostdin -loglevel warning \
  -f alsa -i "$DEV" -t "$DUR" \
  -af "pan=mono|c0=0.5*c0+0.5*c1" -ac 1 -ar 16000 \
  -y "$WAV"

python3 - <<PY "$WAV"
import sys, wave, struct, math
p = sys.argv[1]
with wave.open(p) as w:
    raw = w.readframes(w.getnframes())
s = struct.unpack("<" + "h" * (len(raw)//2), raw)
rms = math.sqrt(sum(x*x for x in s)/len(s))
db = 20*math.log10(max(rms,1)/32768)
clip = 100*sum(1 for x in s if abs(x)>=30000)/len(s)
print(f"完成: {p}")
print(f"  RMS ~{db:.1f} dBFS  peak={max(abs(x) for x in s)}  clip%={clip:.2f}")
if db > -10:
    print("  WARN: 仍过响/可能杂音；调低 Rode 增益或换 USB 口后重试")
elif db < -45:
    print("  WARN: 过小；检查是否静音或选错设备")
else:
    print("  OK: 电平大致正常，请用播放器试听")
PY

echo "宿主机路径: ~/Research/percy_data/${SESSION}/audio.wav"
