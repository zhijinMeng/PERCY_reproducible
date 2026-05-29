#!/usr/bin/env bash
# Create analysis venv and install HF deps (no sudo if python3-venv missing).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv-analysis/bin/python3" ]]; then
  python3 -m venv --without-pip "$ROOT/.venv-analysis"
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  "$ROOT/.venv-analysis/bin/python3" /tmp/get-pip.py
fi

"$ROOT/.venv-analysis/bin/pip" install torch --index-url https://download.pytorch.org/whl/cpu
"$ROOT/.venv-analysis/bin/pip" install "transformers>=4.40"

echo "OK. Run:"
echo "  source $ROOT/.venv-analysis/bin/activate"
echo "  python3 text_emotion_7.py --channels vader7,lexicon,hf"
echo "  python3 cross_modal_7x7.py --channels vader7,lexicon,hf"
