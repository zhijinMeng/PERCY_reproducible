#!/usr/bin/env bash
# 一键：进入 ROS1 Docker 并自动连 ARI（source env_ari.sh）。
# 在仓库根执行: ./ros1_ari.sh
# 可选参数与 docker_ros1_noetic/run_ros1_noetic.sh 相同，例如: ./ros1_ari.sh --rebuild
# 临时改机器人/本机 IP（宿主机执行）:
#   export ARI_ROS_MASTER_URI=http://10.68.0.1:11311
#   export ARI_ROS_IP=10.68.0.129
# roslaunch「Unable to contact my own server」: 容器内 env_ari 已对远端 master 默认 ROS_IP=127.0.0.1；
# 若必须走局域网 IP：export ARI_ROS_USE_LOOPBACK=0；本机 IP 仍错可 export ARI_ROS_IP=...
# Publisher 常登记为 ari-27c；run_ros1_noetic.sh 会默认 --add-host ari-27c:<IP>。
# 若 master URI 里不是 IPv4，请显式: export ARI_ROS_PEER_IP=10.68.0.1
# 不需要该映射时: export ARI_DOCKER_EXTRA_HOST=0
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/docker_ros1_noetic/run_ros1_noetic.sh" --ari "$@"
