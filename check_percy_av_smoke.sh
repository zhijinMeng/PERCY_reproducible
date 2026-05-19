#!/usr/bin/env bash
# 新 Docker / 新环境：麦克风 + 机器人 topic + 可选短录制 A/V 同步
# 在容器内执行:
#   source /workspace/percy_ws/devel/setup.bash
#   source /workspace/docker_ros1_noetic/env_ari.sh
#   bash /workspace/check_percy_av_smoke.sh
#   bash /workspace/check_percy_av_smoke.sh --record-sec 12   # 需机器人相机+网
set -euo pipefail

RECORD_SEC=0
while [[ "${1:-}" == -* ]]; do
  case "$1" in
    --record-sec) RECORD_SEC="${2:-12}"; shift 2 ;;
    -h|--help)
      echo "用法: $0 [--record-sec N]"
      echo "  无参数: 麦克风 + ROS topic 快检（约 20s）"
      echo "  --record-sec 12: 额外录 N 秒并检查 av_sync_error_sec"
      exit 0
      ;;
    *) echo "未知: $1"; exit 1 ;;
  esac
done

fail() { echo "[FAIL] $*" >&2; exit 1; }
warn() { echo "[WARN] $*"; }
ok() { echo "[OK]   $*"; }

source /opt/ros/noetic/setup.bash
[[ -f /workspace/percy_ws/devel/setup.bash ]] || fail "先: cd /workspace/percy_ws && catkin_make && source devel/setup.bash"
source /workspace/percy_ws/devel/setup.bash
[[ -f /workspace/docker_ros1_noetic/env_ari.sh ]] && source /workspace/docker_ros1_noetic/env_ari.sh

echo "========== 1. 宿主机 USB 麦（ALSA）=========="
if ! command -v arecord >/dev/null; then
  echo "[FAIL] 容器内无 arecord（当前镜像未含 alsa-utils）"
  echo "  快速修复（本容器有效，退出后需重做或 --rebuild）:"
  echo "    bash /workspace/docker_ros1_noetic/ensure_alsa_utils.sh"
  echo "  持久修复（宿主机）:"
  echo "    cd ~/Research && ./ros1_ari.sh --rebuild"
  exit 1
fi
echo "--- arecord -l ---"
arecord -l || true
_dev=""
if [[ -f /workspace/docker_ros1_noetic/detect_host_usb_mic.sh ]]; then
  # shellcheck source=/dev/null
  source /workspace/docker_ros1_noetic/detect_host_usb_mic.sh
  _dev="$(percy_host_usb_mic_device || true)"
fi
if [[ -z "$_dev" ]]; then
  fail "未检测到 USB 麦；确认 Rode 已插笔记本且进容器时带 --audio"
fi
ok "检测到 ALSA 设备: $_dev"

echo ""
echo "========== 2. 启动 host_rode_capture（5s）=========="
_rode_pid=""
cleanup_rode() {
  if [[ -n "$_rode_pid" ]] && kill -0 "$_rode_pid" 2>/dev/null; then
    kill "$_rode_pid" 2>/dev/null || true
    wait "$_rode_pid" 2>/dev/null || true
  fi
}
trap cleanup_rode EXIT

roslaunch percy host_rode_capture.launch >/tmp/host_rode_smoke.log 2>&1 &
_rode_pid=$!
sleep 2
if ! kill -0 "$_rode_pid" 2>/dev/null; then
  echo "--- host_rode_capture 日志 ---"
  cat /tmp/host_rode_smoke.log || true
  fail "host_rode_capture 已退出"
fi
grep -q "device=plughw" /tmp/host_rode_smoke.log && ok "采集节点已启动（见 /tmp/host_rode_smoke.log）" || warn "日志中未见 device=plughw"

_hz_out="$(timeout 6 rostopic hz /audio/rode -w 5 2>&1)" || true
echo "$_hz_out" | tail -5
if echo "$_hz_out" | grep -qE 'average rate: (9|1[0-5])'; then
  ok "/audio/rode ~10 Hz（100ms chunk 正常）"
elif echo "$_hz_out" | grep -q 'average rate'; then
  warn "/audio/rode 有数据但频率异常，请对着麦说话再测"
else
  fail "/audio/rode 无数据；检查 --audio 挂载与 Device busy"
fi

# 3s 原始录音 RMS
_wav="/tmp/rode_smoke_$$.wav"
echo ""
echo "========== 3. 3s 原始录音电平 =========="
if arecord -D "$_dev" -f S16_LE -r 16000 -c 1 -d 3 "$_wav" 2>/dev/null; then
  python3 - <<'PY' "$_wav"
import sys, wave, struct, math
p = sys.argv[1]
with wave.open(p, "rb") as w:
    raw = w.readframes(w.getnframes())
n = len(raw) // 2
if n < 1:
    print("[FAIL] 空 wav"); sys.exit(1)
    samples = struct.unpack("<" + "h" * n, raw[: n * 2])
rms = math.sqrt(sum(s * s for s in samples) / n)
peak = max(abs(s) for s in samples)
dbfs = 20 * math.log10(max(rms, 1) / 32768.0)
print(f"  RMS={rms:.0f}  peak={peak}  ~{dbfs:.1f} dBFS")
if dbfs < -50:
    print("[WARN] 电平过低；请对着 Rode 说话重测")
    sys.exit(2)
if dbfs > -6:
    print("[WARN] 电平过高，可能削波")
else:
    print("[OK]   电平正常（说话时应约 -30～-15 dBFS）")
PY
  _py=$?
  [[ "$_py" -eq 0 ]] || [[ "$_py" -eq 2 ]] || fail "RMS 分析失败"
  rm -f "$_wav"
else
  warn "arecord 3s 失败（可能与 roslaunch 争用设备）；停掉 capture 后单独 arecord 试"
fi

echo ""
echo "========== 4. 机器人 topic（各约 5s）=========="
_ping_ok=0
_mh="${ROS_MASTER_URI#http://}"
_mh="${_mh#https://}"
_mh="${_mh%%:*}"
if ping -c1 -W2 "$_mh" 2>/dev/null | grep -q '1 received'; then
  ok "ping $_mh"
  _ping_ok=1
else
  warn "ping $_mh 失败，以下 topic 可能无数据"
fi

_cam="$(timeout 6 rostopic hz /head_front_camera/color/image_raw -w 5 2>&1)" || true
echo "$_cam" | tail -3
if echo "$_cam" | grep -qE 'average rate: (2[0-9]|3[0-9])'; then
  ok "头相机 ~25–30 Hz"
elif echo "$_cam" | grep -q 'average rate'; then
  warn "头相机有数据但帧率偏低"
else
  [[ "$_ping_ok" -eq 1 ]] && warn "头相机无数据（相机节点未开？）" || warn "跳过头相机（未连机器人）"
fi

_ch0="$(timeout 6 rostopic hz /audio/channel0 -w 5 2>&1)" || true
echo "$_ch0" | tail -3
if echo "$_ch0" | grep -q 'average rate'; then
  ok "机载 /audio/channel0 有数据（录制对齐仍可用 onboard）"
else
  warn "机载 /audio/channel0 无数据（若只用 Rode 可忽略）"
fi

if [[ "$RECORD_SEC" -gt 0 ]]; then
  echo ""
  echo "========== 5. 短录制 A/V 同步 (${RECORD_SEC}s) =========="
  export PERCY_DATA_DIR="${PERCY_DATA_DIR:-/workspace/percy_data}"
  _sid="smoke_$(date +%H%M%S)"
  _dir="${PERCY_DATA_DIR}/${_sid}"
  mkdir -p "$_dir"
  cleanup_rode
  trap - EXIT
  roslaunch percy record_aligned.launch session_id:="$_sid" audio_source:=host_usb &
  _rec_pid=$!
  echo "录制中 ${RECORD_SEC}s … 请保持机器人头相机有画面"
  sleep "$RECORD_SEC"
  kill -INT "$_rec_pid" 2>/dev/null || true
  wait "$_rec_pid" 2>/dev/null || true
  echo "等待 finalize（最多 120s）…"
  _t=0
  while [[ ! -f "$_dir/finalize.done" ]] && [[ "$_t" -lt 120 ]]; do
    sleep 2
    _t=$((_t + 2))
  done
  if [[ ! -f "$_dir/recording_meta.json" ]]; then
    fail "无 recording_meta.json；见 $_dir"
  fi
  echo "--- recording_meta（关键字段）---"
  grep -E 'finalize_status|av_sync_error|video_duration|audio_duration|frames|video_stamp' \
    "$_dir/recording_meta.json" || true
  _err="$(python3 -c "import json; m=json.load(open('$_dir/recording_meta.json')); print(m.get('av_sync_error_sec','?'))")"
  _fin="$(python3 -c "import json; m=json.load(open('$_dir/recording_meta.json')); print(m.get('finalize_status','?'))")"
  if [[ "$_fin" == "ok" ]] && python3 -c "import json; e=float(json.load(open('$_dir/recording_meta.json')).get('av_sync_error_sec',99)); exit(0 if abs(e)<0.1 else 1)" 2>/dev/null; then
    ok "A/V 同步 av_sync_error_sec=$_err (<0.1s)"
  elif [[ "$_fin" == "ok" ]] && python3 -c "import json; e=float(json.load(open('$_dir/recording_meta.json')).get('av_sync_error_sec',99)); exit(0 if abs(e)<0.5 else 1)" 2>/dev/null; then
    warn "A/V 可接受 av_sync_error_sec=$_err (<0.5s)"
  else
    fail "finalize=$_fin av_sync_error_sec=$_err；宿主机检查: ~/Research/percy_data/$_sid/"
  fi
  ok "输出目录: $_dir （宿主机 ~/Research/percy_data/$_sid）"
fi

echo ""
echo "========== 完成 =========="
if [[ "$RECORD_SEC" -eq 0 ]]; then
  echo "若需验证 stamp 对齐录制，再运行:"
  echo "  bash /workspace/check_percy_av_smoke.sh --record-sec 12"
fi
