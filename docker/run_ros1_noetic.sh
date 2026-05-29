#!/usr/bin/env bash
# 在本机启动 ROS1 Noetic，挂载 ~/Research 到容器内 /workspace。
# 默认使用本地构建镜像（含 ros-noetic-audio-common-msgs，供 percy_ws 编译/运行）。
set -euo pipefail

SMALL=0
FORCE_PULL=0
REBUILD=0
ARI=0
while [[ "${1:-}" == -* ]]; do
  case "$1" in
    --small) SMALL=1 ;;
    --pull) FORCE_PULL=1 ;;
    --rebuild) REBUILD=1 ;;
    --ari) ARI=1 ;;
    -h|--help)
      echo "用法: $0 [--ari] [--small] [--pull] [--rebuild]"
      echo "  默认：本地镜像 research/ros1-noetic-percy:local（Dockerfile 含 audio_common_msgs）"
      echo "  --ari     进入容器后自动 source env_ari.sh（连机器人 roscore）"
      echo "  --small   使用 ros:noetic-ros-base（更小；进容器后需自行 apt 装 ros-noetic-audio-common-msgs）"
      echo "  --pull    仅在使用官方镜像变量时 docker pull"
      echo "  --rebuild 强制重新 docker build 本地镜像"
      echo "  环境变量 ROS1_DOCKER_IMAGE 可指定任意镜像名"
      echo "  连机器人前可 export ARI_ROS_MASTER_URI / ARI_ROS_IP，会传入容器供 env_ari.sh 使用"
      echo "  可选: ARI_ROS_PEER_IP=机器人IP（Publisher 主机名解析，默认从 MASTER_URI 主机段或 10.68.0.1）"
      echo "       ARI_ROS_ROBOT_HOSTNAME=ari-27c  ARI_DOCKER_EXTRA_HOST=0 可关闭 --add-host"
      exit 0
      ;;
    *) echo "未知参数: $1 （用 --help）"; exit 1 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_WS="${ROS1_WS_HOST_DIR:-$HOME/Research}"
CONTAINER_WS="/workspace"
LOCAL_IMAGE="${ROS1_LOCAL_IMAGE:-research/ros1-noetic-percy:local}"

if ! docker info >/dev/null 2>&1; then
  echo "无法连接 Docker（permission denied 或服务未启动）。请依次检查："
  echo "  1) sudo systemctl status docker"
  echo "  2) groups | grep -q docker || echo '执行: sudo usermod -aG docker \"\$USER\" 然后重新登录或: newgrp docker'"
  exit 1
fi

if [[ -n "${ROS1_DOCKER_IMAGE:-}" ]]; then
  IMAGE="$ROS1_DOCKER_IMAGE"
  if [[ "$FORCE_PULL" -eq 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "拉取镜像: $IMAGE"
    docker pull "$IMAGE"
  fi
elif [[ "$SMALL" -eq 1 ]]; then
  IMAGE="ros:noetic-ros-base"
  if [[ "$FORCE_PULL" -eq 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    docker pull "$IMAGE"
  fi
  echo "注意: ros-base 不含 audio_common_msgs，编译 percy 前请执行:"
  echo "  apt-get update && apt-get install -y ros-noetic-audio-common-msgs"
else
  IMAGE="$LOCAL_IMAGE"
  if [[ "$REBUILD" -eq 1 ]] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "构建本地镜像: $IMAGE（首次或 --rebuild 会稍慢）"
    docker build -t "$IMAGE" "$SCRIPT_DIR"
  fi
fi

X11_ARGS=()
if [[ -n "${DISPLAY:-}" ]]; then
  X11_ARGS=( -e "DISPLAY=$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix )
fi

echo "镜像: $IMAGE"
echo "挂载: $HOST_WS -> $CONTAINER_WS"
echo "进入后已 source /opt/ros/noetic/setup.bash。"
if [[ "$ARI" -eq 1 ]]; then
  echo "已启用 --ari：将自动 source /workspace/docker_ros1_noetic/env_ari.sh（ROS_MASTER_URI / ROS_IP）。"
else
  echo "连机器人: source /workspace/docker_ros1_noetic/env_ari.sh 或使用: $0 --ari"
fi
echo "percy_ws: cd /workspace/percy_ws && source devel/setup.bash"

ARI_ENV=()
[[ -n "${ARI_ROS_MASTER_URI:-}" ]] && ARI_ENV+=( -e "ARI_ROS_MASTER_URI=$ARI_ROS_MASTER_URI" )
[[ -n "${ARI_ROS_IP:-}" ]] && ARI_ENV+=( -e "ARI_ROS_IP=$ARI_ROS_IP" )

# Publisher 常在 master 上登记为 http://ari-27c:xxxxx/；若容器内无法解析该主机名，会出现
# rostopic info 有 Publishers 但 rostopic hz 一直 no new messages。映射到机器人 IP（默认同网段 master）。
ADD_HOST_ARGS=()
if [[ "${ARI_DOCKER_EXTRA_HOST:-1}" != "0" ]]; then
  _peer="${ARI_ROS_PEER_IP:-}"
  if [[ -z "$_peer" && -n "${ARI_ROS_MASTER_URI:-}" ]]; then
    _m="${ARI_ROS_MASTER_URI#http://}"
    _m="${_m#https://}"
    _peer="${_m%%:*}"
  fi
  if [[ -z "$_peer" || ! "$_peer" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    _peer="10.68.0.1"
  fi
  _robot_host="${ARI_ROS_ROBOT_HOSTNAME:-ari-27c}"
  ADD_HOST_ARGS=( --add-host "${_robot_host}:${_peer}" )
fi

if [[ "$ARI" -eq 1 ]]; then
  START_CMD='source /opt/ros/noetic/setup.bash && source /workspace/docker_ros1_noetic/env_ari.sh && exec bash'
else
  START_CMD='source /opt/ros/noetic/setup.bash && exec bash'
fi

exec docker run -it --rm \
  --net=host \
  "${ADD_HOST_ARGS[@]}" \
  -e PYTHONUNBUFFERED=1 \
  "${ARI_ENV[@]}" \
  "${X11_ARGS[@]}" \
  -v "$HOST_WS:$CONTAINER_WS" \
  -w "$CONTAINER_WS" \
  "$IMAGE" \
  bash -lc "$START_CMD"
