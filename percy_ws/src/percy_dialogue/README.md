# percy_dialogue — 实时轮流对话

与 **`percy`**（stamp 对齐录制）配合，用于 PERCY benchmark 采集。

主流程见 [`~/Research/experience/PERCY实时对话与Benchmark采集说明.md`](../../../experience/PERCY实时对话与Benchmark采集说明.md)。

## 依赖

- `percy`（同工作区）
- `pal_interaction_msgs`、`audio_common_msgs`
- Python：`openai==1.14.1`、`webrtcvad` → `~/Research/docker_ros1_noetic/install_dialogue_deps.sh`
- `OPENAI_API_KEY`；可选 `PERCY_DATA_DIR`

## 一键采集（推荐）

```bash
bash /workspace/record_dialogue_session.sh <session_id>
```

等价于 `live_session.launch`（`host_rode_capture` + `stamp_aligned_recorder` + `live_dialogue`）。

## Launch

| Launch | 说明 |
|--------|------|
| `live_session.launch` | 对话 + 对齐 A/V（推荐） |

```bash
source /workspace/percy_ws/devel/setup.bash
export PERCY_DATA_DIR=/workspace/percy_data
roslaunch percy_dialogue live_session.launch session_id:=18
```

常用参数：`end_silence_sec`、`max_utterance_sec`、`vad_mode`、`audio_gain`（见主文档）。

## Session 产出（`$PERCY_DATA_DIR/<id>/`）

| 文件 | 说明 |
|------|------|
| `chat_history.json` | 对话文本 |
| `dialogue_timeline.json` | 相对 session t0 的时间轴 |
| `session_events.jsonl` | 含 `utterance_end` 原因等 |
| `utterances/user_*.wav` | 用户每轮语音切片 |
| `benchmark_manifest.json` | `build_benchmark_manifest.py` 生成 |

时间轴 **t=0** 来自 `/percy/session/t0`（与 `audio.wav` 起点一致）。

## 工具

```bash
rosrun percy_dialogue tts_test.py "Hello"
rosrun percy_dialogue build_benchmark_manifest.py /workspace/percy_data/18
python3 .../scripts/test_vad_eou.py --timeline /workspace/percy_data/18/utterances/user_0001.wav
rosservice call /percy_live/end_turn "{}"
```

离线 Whisper 对齐评测：`rosrun percy benchmark_asr.sh <session_dir>`（`percy` 包）。
