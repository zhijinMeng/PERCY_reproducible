#!/usr/bin/env bash
# 宿主机 / 容器内：检测笔记本 USB 麦（Rode NT-USB+ 等），供 ros1_ari / env_ari 使用。
# 用法:
#   source detect_host_usb_mic.sh && echo "$PERCY_HOST_USB_ALSA"
#   ./detect_host_usb_mic.sh --present && echo yes
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT="$(cd "$_SCRIPT_DIR/.." && pwd)"

_percy_detect_py() {
  # 宿主机优先用 src（devel 包装常写死 /workspace/...，在宿主机上会 FileNotFound）
  for _p in \
    "$_ROOT/percy_ws/src/percy/scripts/host_usb_mic_detect.py" \
    "$_ROOT/percy_ws/devel/lib/percy/host_usb_mic_detect.py"; do
    if [[ -f "$_p" ]]; then
      if [[ "$_p" == *"/devel/lib/"* ]] && head -5 "$_p" 2>/dev/null | grep -q '/workspace/'; then
        continue
      fi
      echo "$_p"
      return 0
    fi
  done
  return 1
}

percy_host_usb_mic_device() {
  local _py="" _out=""
  if _py="$(_percy_detect_py 2>/dev/null)" && command -v python3 >/dev/null 2>&1; then
    _out="$(python3 "$_py" --print-device 2>/dev/null || true)"
    if [[ -n "$_out" ]]; then
      printf '%s' "$_out"
      return 0
    fi
  fi
  if command -v arecord >/dev/null 2>&1; then
    arecord -l 2>/dev/null | awk '
      /^card [0-9]+:/ {
        line=$0
        if (line ~ /NTUSB|NT-USB|RODE|RØDE|Rode/) {
          match(line, /^card ([0-9]+):/, a)
          if (a[1] != "") { printf "plughw:%s,0\n", a[1]; exit }
        }
      }
    '
    return 0
  fi
  if [[ -f /proc/asound/cards ]]; then
    awk '
      /NTUSB|NT-USB|RODE|RØDE|Rode/ {
        match($0, /^[[:space:]]*([0-9]+)/, a)
        if (a[1] != "") { printf "plughw:%s,0\n", a[1]; exit }
      }
    ' /proc/asound/cards
  fi
}

percy_host_usb_mic_present() {
  [[ -n "$(percy_host_usb_mic_device)" ]]
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    --present)
      percy_host_usb_mic_present
      ;;
    --print-device)
      percy_host_usb_mic_device
      ;;
    *)
      echo "用法: $0 --present | --print-device" >&2
      exit 2
      ;;
  esac
fi
