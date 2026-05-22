#!/usr/bin/env bash
# 宿主机一次性安装 NVIDIA Container Toolkit，使 docker run --gpus all 可用。
# 用法（在 ~/Research 下，需 sudo）:
#   bash docker_ros1_noetic/install_nvidia_container_toolkit.sh
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "请用 sudo 运行: sudo bash $0"
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1 || ! nvidia-smi >/dev/null 2>&1; then
  echo "错误: 宿主机 nvidia-smi 不可用，请先安装 NVIDIA 驱动。"
  exit 1
fi

echo "NVIDIA 驱动:"
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader

if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 未找到 docker。"
  exit 1
fi

distro="$(. /etc/os-release && echo "${ID}${VERSION_ID}")"
case "$distro" in
  ubuntu22.04|ubuntu24.04|ubuntu20.04|debian12|debian11) ;;
  *)
    echo "警告: 未在列表中验证的发行版 $distro，将尝试 stable 源 …"
    ;;
esac

install -d -m 0755 /usr/share/keyrings
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list

apt-get update
apt-get install -y nvidia-container-toolkit

nvidia-ctk runtime configure --runtime=docker
systemctl restart docker

echo ""
echo "验证 Docker GPU …"
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi

echo ""
echo "完成。之后可用: cd ~/Research && ./ros1_ari.sh"
