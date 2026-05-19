# percy_dialogue — 轮流对话与时间轴

与 **`percy`**（stamp 对齐录制）解耦，便于单独迭代对话逻辑。

现场启动、TTS 音量、故障表：[`~/Research/experience/PERCY轮流对话启动说明.md`](../../../experience/PERCY轮流对话启动说明.md)

## 依赖

- `percy`（同工作区；联合实验时用 `benchmark_session.launch`）
- `pal_interaction_msgs`、`audio_common_msgs`
- Python：`openai==1.14.1`、`webrtcvad`、`nltk`（VADER）→ `~/Research/docker_ros1_noetic/install_dialogue_deps.sh`
- `OPENAI_API_KEY`；可选 `PERCY_DATA_DIR`

## Launch

| Launch | 说明 |
|--------|------|
| `turn_dialogue.launch` | 仅对话 |
| `benchmark_session.launch` | `percy` 录制 + 本包对话 |

```bash
source ~/Research/percy_ws/devel/setup.bash
export PERCY_DATA_DIR=~/Research/percy_data

roslaunch percy_dialogue turn_dialogue.launch session_id:=dialogue01

调参备忘：

| 现象 | 参数 |
|------|------|
| 要大喊 / 小声听不见 | `vad_mode:=0`（更灵敏）、`audio_gain:=2.8`～`3.0` |
| 延迟高 | `end_silence_sec:=0.9`、`min_whisper_sec:=0.6`、`post_tts_mute_sec:=1.0` |
| 杂音 `you`、幻听变多 | `vad_mode:=1`、`audio_gain:=2.5` |
| 句内稍停就被截断 | 加大 `end_silence_sec:=1.3` |
| 机器人回声被当人声 | `post_tts_mute_sec:=2.0` |
| 稳态底噪 | `enable_noise_reduce:=true`（默认开）；日志看 `Whisper X.XXs` / `GPT X.XXs` |
| 关 VADER（仅文本对话） | `enable_vader:=false` |
| 开视觉+0.6/0.4 融合 | 另启 `emotion_model` + `enable_visual_affect:=true` |
roslaunch percy_dialogue benchmark_session.launch session_id:=13
```

## Session 产出（写入 `$PERCY_DATA_DIR/<id>/`）

| 文件 | 说明 |
|------|------|
| `chat_history.json` | 对话文本；user 轮含 `sentiment` / `sentiment_score` / `emotion_visual` / `affect_fused`（与 MERCI 文稿一致） |
| `dialogue_timeline.json` | 相对 `recording_meta.first_image_stamp` 的 `t_*_sec` |
| `utterance_*.wav` | 用户语音片段 |

与录制对齐时，需同 session 下存在 `percy` 写入的 `recording_meta.json`（`benchmark_session.launch` 会自动满足）。

## 工具

```bash
rosrun percy_dialogue tts_test.py "Hello"
rosrun percy_dialogue build_benchmark_manifest.py ~/Research/percy_data/13
```

离线 Whisper 仍在 **`percy`**：`rosrun percy benchmark_asr.sh <session_dir>`
