# PERCY 实时对话 + Benchmark 采集（推荐流程）

笔记本 Docker 连 ARI 机器人：**外置 USB 麦** + **头相机 raw 图**，一边实时轮流对话，一边落盘对齐的音视频与对话日志。

相关文档：

| 文档 | 用途 |
|------|------|
| [`../percy_surveys/README.md`](../percy_surveys/README.md) | 本地事前/事后问卷、`profile.json` |
| [`DOCKER_ROS1_连机器人说明.md`](DOCKER_ROS1_连机器人说明.md) | 网线、Docker、`env_ari.sh`、话题 |
| [`PERCY轮流对话启动说明.md`](PERCY轮流对话启动说明.md) | TTS 音量、仅对话、故障 |
| [`录制对齐音视频说明.md`](录制对齐音视频说明.md) | 仅录制、离线 Whisper、A/V 细节 |

---

## 1. 系统架构（简图）

```
[USB 麦] → host_rode_capture → /audio/rode ─┬→ live_dialogue (VAD→Whisper→GPT→TTS)
[头相机] → /head_front_camera/.../image_raw → stamp_aligned_recorder → audio.wav + whole_video.mp4
录制开始 → /percy/session/t0 (latched) → 对话时间轴 t=0
```

- **入口**：`record_dialogue_session.sh` → `live_session.launch`
- **对话节点**：`live_dialogue.py`（WebRTC VAD，问候播完后再收用户语音）

---

## 2. 一次性准备

### 2.1 密钥与网络

```bash
cd ~/Research
cp .env.local.example .env.local
# 编辑：OPENAI_API_KEY、ARI_ROS_IP（本机连机器人网卡 IP，如 10.68.0.130）
```

### 2.2 编译工作空间（改代码后都要做）

```bash
cd ~/Research
./ros1_ari.sh          # 插好 Rode 会自动 --audio
# 容器内：
cd /workspace/percy_ws && catkin_make && source devel/setup.bash
```

### 2.3 实验前速查

| 项 | 命令 |
|----|------|
| 机器人 | `ping -c 2 10.68.0.1` |
| 相机 | `rostopic hz /head_front_camera/color/image_raw -w 5` |
| 外置麦 | `rostopic hz /audio/rode -w 5` |
| 快检 | `bash /workspace/check_percy_av_smoke.sh` |

---

## 3. MERCI 完整采集（推荐：问卷 + 对话 + 反馈）

一条命令编排 **事前问卷 → Docker 对话录制 → 事后问卷**（session 编号自定，如 `28`）。

### 3.0 权限（宿主机填问卷前，做一次）

若 `percy_data` 由 Docker 创建、属主为 root：

```bash
sudo chown -R "$(whoami):$(whoami)" ~/Research/percy_data
```

### 3.0.1 宿主机：编排脚本

```bash
cd ~/Research
./run_merci_session.sh 28 audio_gain:=1.2 end_silence_sec:=1.0 vad_mode:=2
```

| 步骤 | 在哪执行 | 说明 |
|------|----------|------|
| 1 事前问卷 | **宿主机** 浏览器 | Submit 后生成 `profile.json` |
| 2 对话+录制 | **Docker**（见下） | 脚本会提示命令；**勿在本终端 Ctrl+C 整个 merci 脚本** |
| 3 事后问卷 | **宿主机** 按 Enter 后浏览器 | 对话结束回到终端 A 再按 Enter |

Docker 里对话（终端 B）：

```bash
cd ~/Research && ./ros1_ari.sh
source /workspace/docker_ros1_noetic/env_ari.sh
# 首次：cd /workspace/PERCY && catkin_make && source devel/setup.bash
./record_dialogue_session.sh 28 audio_gain:=1.2 end_silence_sec:=1.0 vad_mode:=2
```

**选项**

| 参数 | 说明 |
|------|------|
| `--skip-pre` | 跳过事前问卷（无 persona） |
| `--skip-post` | 跳过事后问卷 |
| `--force-pre` | 强制重填事前问卷 |
| `--run-dialogue` | 仅在 **Docker 内** 一条龙（含对话，不推荐宿主机用） |

**分步脚本**（与上面等价）：`run_pre_survey.sh` / `record_dialogue_session.sh` / `run_post_survey.sh`

**当前默认对话行为**（`live_session.launch` / `live_dialogue.py`）：

- 读 `profile.json` → persona prompt + **每 3 轮用户话换 profile 话题**
- 换话题时：**收尾只共情、不追问** → 再 **只问 1 个新话题问题**
- `enable_affect_prompt:=true`：0.6/0.4 融合情感注入 GPT
- 双通道情感仍写入 `chat_history.json`（VADER + 视觉 FER）

**相机未就绪**：录制会卡在 `had_image=False`，直到头相机有数据；对话最多等 `t0` 约 60s 后会 fallback 开口，但 **无对齐 A/V**。先 `rostopic hz /head_front_camera/color/image_raw`，有 hz 再录。

---

## 4. 一键采集（仅对话 + A/V，无问卷）

若已有人工填好的 `profile.json` 或不需要问卷，可直接：

### 4.1 启动（完整 PERCY：对话 + A/V + VADER + 视觉 FER）

```bash
# 宿主机
cd ~/Research
./set_robot_volume.sh
./ros1_ari.sh

# 容器内 — 首次准备（各做一次）
cd /workspace/PERCY && source /opt/ros/noetic/setup.bash && catkin_make && source devel/setup.bash
bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh
bash /workspace/docker_ros1_noetic/install_emotion_model_deps.sh
cd /workspace/percy_ws && catkin_make && source devel/setup.bash
bash /workspace/check_percy_affect_ready.sh

# 一键采集（自动带 streamdata.py，若 PERCY 已编译）
bash /workspace/record_dialogue_session.sh 20
```

仅文本情感、不要视觉 FER（减轻 CPU 负载）：

```bash
PERCY_SKIP_EMOTION_MODEL=1 bash /workspace/record_dialogue_session.sh 20
```

### 4.2 使用流程

1. 日志出现 `Recording -> ... (t0=...)` 与 `Session t0 from /percy/session/t0`
2. 机器人问候 → **`Ready — speak (pause ~0.8s to end turn)`**
3. **对着外置麦**说一两句 → 停顿约 **0.8s** → 终端 `You said:` → 机器人回复
4. 重复多轮；结束：**Ctrl+C 一次**（会 wait_finalize + 写 manifest）

### 4.3 手动截句（可选）

说完不想等静音：

```bash
rosservice call /percy_live/end_turn "{}"
```

### 4.4 常用参数

```bash
bash /workspace/record_dialogue_session.sh 18 \
  end_silence_sec:=1.0 \
  post_tts_mute_sec:=1.5 \
  vad_mode:=3 \
  max_utterance_sec:=25.0
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `vad_backend` | **silero** | 端点检测（抗风扇）；旧版 `webrtc` 见 `vad_mode` |
| `silero_threshold` | 0.5 | Silero 语音概率阈值（越高越不易误开） |
| `end_silence_sec` | 1.0 | 映射为 Silero `min_silence_duration_ms` |
| `vad_mode` | 3 | 仅 `vad_backend:=webrtc` 时有效 |
| `enable_noise_gate` | false | 仅 WebRTC 回退路径；Silero 默认关闭 |
| `noise_gate_profile_wav` | `__auto__` | 自动读 `percy_data/lab_ambient_day_29/ambient_raw.wav` 标定门限 |
| `noise_gate_margin` | 1.35 | 环境底噪标定，约 **1100**（开句用 `×0.65`） |
| `noise_gate_hangover_ratio` | **1.0** | 句中已不用 RMS 门限时可忽略 |
| `noise_gate_start_ratio` | 0.5 | 开句用较低门限；句中用满门限结束 |
| `noise_gate_min_active_frames` | 3 | 连续高能帧才刷新「最后说话」 |
| `noise_gate_rms` | 0 | 手动门限（>0 覆盖自动标定） |
| `end_silence_sec` | 0.8 | 静音多久判定一句结束 |
| `min_speech_sec` | 0.8 | 至少说这么久才允许 `End silence` |
| `min_whisper_sec` | 1.2 | 短于此不送 Whisper（过滤 ~1s 风扇幻听） |
| `noise_gate_only_at_start` | true | **仅开句**用 RMS 门限；句中只靠 VAD（避免把你语音 RMS 当噪音滤掉） |
| `noise_gate_start_frames` | 4 | 连续 4 帧过开句门限才真正 `Speech start` |
| `reject_short_hallucinations` | true | 过滤短片段幻听（如 Seriously / That's your mission） |
| `post_tts_mute_sec` | 1.0 | TTS 后冷却，减少机器人尾音触发开句 |
| `post_tts_mute_sec` | 0.6 | TTS 后冷却（防机器人回声进外置麦）；若 `You said:` 出现机器人自己的话可调到 1.0～1.5 |
| `max_utterance_sec` | 25 | 最长一句，超时强制送 ASR（兜底；正常靠 Silero 静音截断） |
| `enable_affect` | true | MERCI 双通道：VADER + 视觉情感 |
| `enable_visual_affect` | true | 订阅 `emotiondetect_result`（见下文：笔记本跑 `streamdata.py`） |
| `enable_affect_prompt` | **true** | 融合情感注入 GPT；仅要标注可关：`enable_affect_prompt:=false` |
| `enable_profile` | true | 读 `profile.json` persona + 换话题 |
| `profile_followups_per_topic` | 3 | 每个 profile 话题跟几轮再换 |
| `affect_w_visual` / `affect_w_text` | 0.6 / 0.4 | 与论文一致 |

**情感模型（与 PERCY / MERCI 论文一致）**

| 通道 | 模型 | ROS / 数据 |
|------|------|------------|
| 文本 | **NLTK VADER**（Whisper 转写后） | 本地 Python，compound ±0.05 |
| 视觉 | **MobileNetV2 + 人脸检测**（`PERCY/src/emotion_model`） | **笔记本 Docker** 订阅机器人 `/head_front_camera/color/image_raw`，发布 `emotiondetect_result` |
| 融合 | 0.6 视觉 + 0.4 文本 | 写入 `chat_history` / `dialogue_timeline` |

**视觉管线（与论文一致，在笔记本 Docker 处理）**

`record_dialogue_session.sh` 会在 `live_session.launch` 里自动启动 `emotion_model/streamdata.py`（需已 `catkin_make` PERCY 并安装 `install_emotion_model_deps.sh`）。

机器人只提供 `/head_front_camera/color/image_raw`；本机 **CPU** 内推理并发布 `emotiondetect_result`（约 5Hz）。权重 `latest_model_099_94.7200.pth`。

自检：

```bash
rostopic hz /head_front_camera/color/image_raw -w 3
rostopic hz emotiondetect_result -w 3
```

无 FER 时视觉记为 `neutral`，VADER 仍可用。延迟若偏大，可先 `PERCY_SKIP_EMOTION_MODEL=1` 对比，再考虑换轻量模型（后续优化）。

---

## 5. 产出目录结构

`~/Research/percy_data/<session_id>/`（容器内 `/workspace/percy_data/...`）：

```
<session_id>/
├── pre_survey.json           # 事前问卷（本地问卷）
├── profile.json              # → GPT persona
├── post_survey.json          # 事后反馈
├── audio.wav                 # 整段外置麦，与视频 stamp 对齐
├── whole_video.mp4           # 头相机 H.264（无内嵌音轨）
├── recording_meta.json
├── finalize.done
├── chat_history.json         # 对话 + 情感字段
├── dialogue_timeline.json    # 带 t_start_sec / t_end_sec（相对 t0）
├── session_events.jsonl      # 调试事件
├── benchmark_manifest.json   # 脚本结束后自动生成
└── utterances/               # 用户每轮语音切片
    ├── user_0001.wav
    └── ...
```

时间轴 **t=0** = 录制开始时的笔记本 `rospy.Time`（话题 `/percy/session/t0`），与 `audio.wav` 起点一致。

---

## 6. 仅录制（无对话）

```bash
roslaunch percy record_aligned.launch session_id:=N
# 或: bash /workspace/record_aligned.sh N
```

对话 + A/V 仍用 **`record_dialogue_session.sh`**。

---

## 7. 打包发给导师

```bash
cd ~/Research
zip -r -9 percy_session_17.zip percy_data/17 -x "percy_data/17/finalize.log"
# 或
cd ~/Research/percy_data
tar -czf percy_session_17.tar.gz --exclude="17/finalize.log" 17
```

大文件是 `whole_video.mp4` 与 `audio.wav`；切片在 `utterances/`。

---

## 8. 常见问题

| 现象 | 处理 |
|------|------|
| 机器人不回应 | 等 `Ready` 再说话；看是否 `You said:`；查 `OPENAI_API_KEY` |
| 每句都顶满 `max_utterance`（白天风扇） | 默认已开 **RMS noise gate**；仍不行则 `vad_mode:=3`、`audio_gain:=1.0`，或 `rosservice call /percy_live/end_turn "{}"` |
| 没说的词出现在 `You said:`（如 Seriously） | 短片段（~1.1s）风扇误触发 + **Whisper 幻听**；已默认 `min_speech_sec:=1.5`、`min_whisper_sec:=1.8`、短句黑名单；重启 launch |
| `Connection error` / DNS | 宿主机 `ping api.openai.com`；节点会自动重试 3 次 |
| 无 `/audio/rode` | 宿主机重进 `./ros1_ari.sh`（带 USB 麦）；`arecord -l` 见 NTUSB |
| 视频未 H.264 / 未 finalize | Ctrl+C 后跑 `bash .../wait_finalize.sh /workspace/percy_data/N` |
| `catkin_make` 失败 `std_srvs` | 已写在 `package.xml`；重新 `catkin_make` |
| 目录权限 root | `sudo chown -R $(whoami) ~/Research/percy_data`；或 `export PERCY_DATA_DIR=$HOME/percy_data` |
| 宿主机 `mkdir /workspace` 失败 | `.env.local` 里 `PERCY_DATA_DIR` 在宿主机会自动映射到 `~/Research/percy_data` |
| 换话题连问两句 | 已拆「收尾陈述 + 新话题一问」；重跑 launch 生效 |
| `had_image=False` 一直不变 | 重启机器人/相机；`rostopic hz /head_front_camera/color/image_raw` |

---

## 9. 代码入口速查

| 路径 | 说明 |
|------|------|
| `run_merci_session.sh` | **MERCI 全流程**（问卷+提示 Docker 对话+事后问卷） |
| `run_pre_survey.sh` / `run_post_survey.sh` | 单独问卷 |
| `record_dialogue_session.sh` | Docker 内对话 + A/V |
| `percy_surveys/` | 问卷 schema 与本地 server |
| `percy_ws/.../launch/live_session.launch` | 推荐 launch |
| `percy_ws/.../scripts/live_dialogue.py` | 实时对话 |
| `percy_ws/.../scripts/stamp_aligned_recorder.py` | A/V 对齐录制 |
| `percy_ws/.../scripts/host_rode_capture.py` | 外置麦 → `/audio/rode` |
| `percy_ws/.../scripts/test_vad_eou.py` | 离线回放 VAD 截断 |

路径根目录：`~/Research`（容器 `/workspace`）。
