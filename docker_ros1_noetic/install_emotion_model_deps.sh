#!/usr/bin/env bash
# PERCY emotion_model：系统 Python 3.8 + CPU 版 PyTorch（streamdata.py 进程内推理）
#
# 容器内（每次新容器执行一次，或 rebuild 镜像后不必重复）:
#   bash /workspace/docker_ros1_noetic/install_emotion_model_deps.sh
set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends python3-pip python3-dev 2>/dev/null || true

python3 -m pip install --no-cache-dir --upgrade "pip<25" setuptools wheel

TORCH_VER="${PERCY_TORCH_VERSION:-2.1.2}"
TV_VER="${PERCY_TORCHVISION_VERSION:-0.16.2}"

echo "安装 CPU 版 PyTorch ${TORCH_VER} …"
python3 -m pip install --no-cache-dir --force-reinstall \
  "torch==${TORCH_VER}" "torchvision==${TV_VER}" \
  --index-url https://download.pytorch.org/whl/cpu \
  --no-deps
# 4.12.x：满足 pydantic/openai（TypeIs），且仍兼容 Python 3.8 + torch 2.1（勿用 4.15+）
python3 -m pip install --no-cache-dir \
  filelock sympy networkx jinja2 fsspec "typing-extensions==4.12.2" \
  "numpy>=1.21,<1.24" pillow requests

python3 -m pip install --no-cache-dir \
  "opencv-python-headless>=4.5,<4.6" \
  "PyYAML>=5.3" \
  easydict tqdm \
  pybaseutils==0.7.6 basetrainer rospkg

python3 -c "
import cv2, torch, requests
from basetrainer.utils import setup_config
print('ok: torch', torch.__version__, 'cv2', cv2.__version__)
"

echo "emotion_model 依赖已安装。请: cd /workspace/PERCY && source /opt/ros/noetic/setup.bash && catkin_make && source devel/setup.bash"
