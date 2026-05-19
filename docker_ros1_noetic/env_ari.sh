#!/usr/bin/env bash
# 在 Docker 容器内 source：连 ARI 上的 roscore
#   source /workspace/docker_ros1_noetic/env_ari.sh
#
# 注意：osrf/ros:noetic 在 source setup.bash 后常把 ROS_MASTER_URI 设成
# http://localhost:11311。若用 ${ROS_MASTER_URI:-机器人地址} 会「保留」localhost，
# 永远连不上真机。本文件改为默认强制指向机器人，除非你事先导出覆盖变量：
#
# roslaunch 报「Unable to contact my own server at [http://ROS_IP:xxxx]」：
#   多为本机无法经「对外 LAN IP」连回自身 XML-RPC（hairpin）。容器内连远端 master 时默认
#   ROS_IP=127.0.0.1（见下）；要改回 LAN：export ARI_ROS_USE_LOOPBACK=0 再 source。
#   未设 ARI_ROS_USE_LOOPBACK 且不用 loopback 时，未设 ARI_ROS_IP 会用 ip route 推断 ROS_IP。

# 与宿主机共用 ~/Research/.env.local（挂载为 /workspace/.env.local）
if [[ -f /workspace/.env.local ]]; then
  set -a
  # shellcheck source=/dev/null
  source /workspace/.env.local
  set +a
fi

export ROS_MASTER_URI="${ARI_ROS_MASTER_URI:-http://10.68.0.1:11311}"

# Docker + 远端 master：默认 ARI_ROS_USE_LOOPBACK=1（ROS_IP=127.0.0.1），避免 roslaunch 自连失败。
if [[ -z "${ARI_ROS_USE_LOOPBACK+x}" && -f /.dockerenv ]]; then
  _mh0="${ROS_MASTER_URI#http://}"
  _mh0="${_mh0#https://}"
  _mh0="${_mh0%%:*}"
  if [[ -n "$_mh0" && "$_mh0" != "localhost" && "$_mh0" != "127.0.0.1" ]]; then
    export ARI_ROS_USE_LOOPBACK=1
  fi
fi

unset ROS_HOSTNAME 2>/dev/null || true

if [[ "${ARI_ROS_USE_LOOPBACK:-0}" == "1" ]]; then
  export ROS_IP="127.0.0.1"
elif [[ -n "${ARI_ROS_IP:-}" ]]; then
  export ROS_IP="$ARI_ROS_IP"
else
  _mh="${ROS_MASTER_URI#http://}"
  _mh="${_mh#https://}"
  _mh="${_mh%%:*}"
  _auto=""
  if [[ -n "$_mh" ]] && command -v ip >/dev/null 2>&1; then
    _auto=$(ip -4 route get "$_mh" 2>/dev/null | awk '{ for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit } }')
  fi
  export ROS_IP="${_auto:-10.68.0.128}"
fi

echo "ROS_MASTER_URI=$ROS_MASTER_URI"
echo "ROS_IP=$ROS_IP"

if [[ -d /dev/snd ]] && ! command -v arecord >/dev/null 2>&1; then
  echo "警告: 已挂载 /dev/snd 但无 arecord → bash /workspace/docker_ros1_noetic/ensure_alsa_utils.sh"
  echo "      或宿主机 ./ros1_ari.sh --rebuild 重建镜像"
fi
if command -v arecord >/dev/null 2>&1 || [[ -f /proc/asound/cards ]]; then
  _detect_sh="/workspace/docker_ros1_noetic/detect_host_usb_mic.sh"
  if [[ -f "$_detect_sh" ]]; then
    # shellcheck source=/dev/null
    source "$_detect_sh"
    PERCY_HOST_USB_ALSA="$(percy_host_usb_mic_device || true)"
    if [[ -n "${PERCY_HOST_USB_ALSA:-}" ]]; then
      export PERCY_HOST_USB_ALSA
      echo "PERCY host USB mic (ALSA): $PERCY_HOST_USB_ALSA  →  roslaunch 默认 audio_source:=host_usb"
    elif [[ -f /.dockerenv ]] && [[ "${ROS1_DOCKER_AUDIO:-}" != "0" ]]; then
      echo "提示: 容器内未看到 USB 麦（常见原因: 本次进容器未挂 --audio）"
      echo "      宿主机插好 Rode 后执行: arecord -l  应见 NTUSB"
      echo "      退出容器再: cd ~/Research && ./ros1_ari.sh  或  ./ros1_ari.sh --audio"
      echo "      换 USB 口只改 card 号，自动识别；须重新进容器挂载 /dev/snd"
    fi
  fi
fi
