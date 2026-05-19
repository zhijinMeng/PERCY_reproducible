#!/usr/bin/env bash
# 终端看不见输入时：source 或 bash fix_tty.sh
stty sane 2>/dev/null || true
stty echo 2>/dev/null || true
echo "TTY: $(stty -a 2>/dev/null | grep -o 'echo' | head -1 || echo 'unknown')"
