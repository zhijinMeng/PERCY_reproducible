#!/usr/bin/env bash
# Extract turn-aligned frames, then compose the multi-row Figure 2 gallery.
set -euo pipefail

OUT="/home/zhijinmeng/Research/paper_writing/Paper_writing/Claude_Writing/Figures"
ROOT="/home/zhijinmeng/Research/HF_Data/percy_data/merci_hf_upload"
PY="python3"
BUILD="$OUT/build_fig_dataset_samples.py"

mkdir -p "$OUT/_build_tmp"

echo "==> Select turns and extract frames"
$PY "$BUILD"

echo "Done: $OUT/fig_dataset_samples.pdf"
