# percy — stamp 对齐 A/V 录制

头相机 + 外置/机载麦克风，按图像 `header.stamp` 切片写入 `audio.wav` 与 `whole_video.mp4`。

主流程（含对话）见 [`~/Research/experience/PERCY实时对话与Benchmark采集说明.md`](../../../experience/PERCY实时对话与Benchmark采集说明.md)。

## Launch

| Launch | 说明 |
|--------|------|
| `record_aligned.launch` | 仅录制 A/V（无对话） |
| `host_rode_capture.launch` | 仅发布 `/audio/rode`（调试麦） |

```bash
roslaunch percy record_aligned.launch session_id:=10
# 默认 audio_source:=host_usb → host_rode_capture + stamp_aligned_recorder
```

结束录制后：`bash .../scripts/wait_finalize.sh /workspace/percy_data/<id>`

## 产出

| 文件 | 说明 |
|------|------|
| `audio.wav` | 16 kHz mono |
| `whole_video.mp4` | H.264（finalize 后） |
| `recording_meta.json` | 含 `av_sync_error_sec`、t0 等 |

## 工具

```bash
rosrun percy rode_capture_sanity.py --out-dir /tmp/rode_sanity
rosrun percy benchmark_asr.sh /workspace/percy_data/10
bash /workspace/record_aligned.sh 10
bash /workspace/check_percy_av_smoke.sh --record-sec 12
```
