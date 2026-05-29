#!/usr/bin/env bash
# 用法: wait_finalize.sh /workspace/percy_data/<session_id>
set -euo pipefail
DIR="${1:?session dir}"
DONE="$DIR/finalize.done"
LOG="$DIR/finalize.log"
echo "等待 finalize 完成: $DIR"
echo "  日志: tail -f $LOG"
while [[ ! -f "$DONE" ]]; do
  if [[ -f "$DIR/recording_meta.json" ]]; then
    st=$(python3 -c "import json; print(json.load(open('$DIR/recording_meta.json')).get('finalize_status',''))" 2>/dev/null || true)
    if [[ "$st" == "failed" ]]; then
      echo "finalize 失败，见 $LOG"
      exit 1
    fi
  fi
  sleep 2
done
echo "finalize 完成。"
if [[ -f "$DIR/recording_meta.json" ]]; then
  python3 -c "
import json
m=json.load(open('$DIR/recording_meta.json'))
print('  video_duration_sec:', m.get('video_duration_sec'))
print('  audio_duration_sec:', m.get('audio_duration_sec'))
print('  av_sync_error_sec:', m.get('av_sync_error_sec'))
"
fi
