#!/usr/bin/env bash
# 容器内快速测 FER 模型能否加载（不需 roscore）
set -euo pipefail
export ROS_PACKAGE_PATH="/workspace/PERCY/src:${ROS_PACKAGE_PATH:-}"
PKG=/workspace/PERCY/src/emotion_model
cd "$PKG"
export MPLBACKEND=Agg
python3 - <<'PY'
import os, sys
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "libs"))
import argparse
from basetrainer.utils import setup_config
from demo import Predictor
parser = argparse.ArgumentParser()
parser.add_argument("-c", "--config_file", default="configs/config.yaml", type=str)
parser.add_argument(
    "-m",
    "--model_file",
    default=(
        "data/pretrained/mobilenet_v2_1.0_CrossEntropyLoss_20230313090258/"
        "model/latest_model_099_94.7200.pth"
    ),
    type=str,
)
parser.add_argument("--device", default="cpu", type=str)
parser.add_argument("--image_dir", default="data/test_image", type=str)
parser.add_argument("--video_file", default=None, type=str)
parser.add_argument("--out_dir", default="output", type=str)
args = parser.parse_args([])
print("loading MobileNetV2 on CPU …")
cfg = setup_config.parser_config(args, cfg_updata=False)
Predictor(cfg)
print("FER CPU smoke OK")
PY
