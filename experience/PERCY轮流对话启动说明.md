# PERCY 轮流对话启动说明（ARI + Docker）

在笔记本 Docker 里连机器人做 **你说一句 → 机器人回一句**。  
**对话 + 对齐 A/V 一键采集**见 [`PERCY实时对话与Benchmark采集说明.md`](PERCY实时对话与Benchmark采集说明.md)（`live_session` + `record_dialogue_session.sh`）。  
本文档侧重 TTS 音量、仅对话、故障；外置麦见 **§2.1**。

更完整的网线 / Docker 见 [`DOCKER_ROS1_连机器人说明.md`](DOCKER_ROS1_连机器人说明.md)。

---

## 0. 每次实验前速查

| 检查项 | 命令 / 期望 |
|--------|-------------|
| 网线千兆 | 宿主机 `ethtool enp3s0 \| grep Speed` → **1000Mb/s** |
| 机器人通 | `ping -c 2 10.68.0.1` |
| 本机 IP | `ip -4 addr show enp3s0`（例 **10.68.0.130**） |
| 音频 | `bash /workspace/check_percy_av_smoke.sh` 或 `rostopic hz /audio/rode -w 5` |
| 头相机（可选） | `rostopic hz /head_front_camera/color/image_raw -w 5` ~25–30 |
| **喇叭音量** | 宿主机 `./set_robot_volume.sh` 或 §5（默认 **60%**，含 `output0`） |

---

## 1. 宿主机配置（一次即可）

在 `~/Research` 使用 **`.env.local`**，不要往文档里抄示例密钥：

```bash
cd ~/Research
cp .env.local.example .env.local
# 编辑 .env.local，填入 OPENAI_API_KEY 与 ARI_ROS_IP 等
```

`./ros1_ari.sh` 与容器内 `env_ari.sh` 会自动加载该文件。  
若曾在 shell 里 `export` 过错误占位文字，请 `unset OPENAI_API_KEY` 或删掉 `~/.bashrc` 里对应行。

---

## 2. 进 Docker

```bash
cd ~/Research
./ros1_ari.sh    # 插上 Rode 后会自动 --audio；不要麦时用 ./ros1_ari.sh --no-audio
```

`source env_ari.sh` 时会打印检测到的 ALSA 设备（如 `plughw:2,0`）。  
首次或镜像旧：`./ros1_ari.sh --rebuild`。

### 2.1 笔记本 USB 麦（自动识别）

麦插在**笔记本**（Dock 亦可）。流程已自动化：

| 步骤 | 行为 |
|------|------|
| `./ros1_ari.sh` | 宿主机 `arecord -l` / `/proc/asound/cards` 发现 NTUSB/RODE → 自动挂载 `--audio` |
| `env_ari.sh` | 打印 `PERCY host USB mic (ALSA): plughw:N,0` |
| `live_session` / `record_aligned` | 默认 `audio_source:=host_usb`，内含 `host_rode_capture` → `/audio/rode` |

**一键对话 + A/V**：

```bash
source /workspace/percy_ws/devel/setup.bash
source /workspace/docker_ros1_noetic/env_ari.sh
export PERCY_DATA_DIR=/workspace/percy_data
bash /workspace/record_dialogue_session.sh 18
```

自检：`rostopic hz /audio/rode -w 3`；日志里 `host_rode_capture: device=plughw:X,0`。

若 `arecord` **Device busy**：宿主机关占用麦的程序；或 `roslaunch percy host_rode_capture.launch alsa_device:=plughw:N,0`。

**分步测试**：

```bash
# 快检：麦 + 可选短 A/V
bash /workspace/check_percy_av_smoke.sh
bash /workspace/check_percy_av_smoke.sh --record-sec 12

# 仅 stamp 对齐录制（无对话）
roslaunch percy record_aligned.launch session_id:=av_test01

rosrun percy rode_capture_sanity.py --out-dir /tmp/rode_sanity
```

采集默认 **`capture_backend:=ffmpeg`**。`host_rode_capture` 默认 `gain:=2.5`，`live_dialogue` 默认 `audio_gain:=2.0`。VAD 误触发时优先降增益，而非再加 gain。

手动检测：`./docker_ros1_noetic/detect_host_usb_mic.sh --print-device`

```bash

容器内：`/workspace` = 宿主机 `~/Research`。

每个新 shell 建议：

```bash
source /opt/ros/noetic/setup.bash
source /workspace/docker_ros1_noetic/env_ari.sh
export ARI_ROS_USE_LOOPBACK=0
export ARI_ROS_IP=10.68.0.130
source /workspace/docker_ros1_noetic/env_ari.sh   # 再 source 一次使 ROS_IP 生效
source /workspace/percy_ws/devel/setup.bash
```

---

## 3. 一次性依赖（新机器 / 清库后）

### 3.1 PAL 消息包（`/tts` 需要）

`pal_msgs` 已在 `~/Research/percy_ws/src/pal_msgs`（除 `pal_interaction_msgs` 外子包带 `CATKIN_IGNORE`）。

Docker 内一键：

```bash
bash /workspace/docker_ros1_noetic/install_pal_msgs.sh
# 或手动:
cd /workspace/percy_ws
source /opt/ros/noetic/setup.bash
catkin_make
source devel/setup.bash
python3 -c "from pal_interaction_msgs.msg import TtsAction; print('OK')"
```

### 3.2 Python（对话节点）

依赖已写入 Docker 镜像；宿主机执行一次 **`./ros1_ari.sh --rebuild`** 后，新容器自带，无需每次 `install_dialogue_deps.sh`。

仅旧镜像或缺包时，容器内补装：

```bash
bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh
```

固定 **openai==1.14.1**（Python 3.8 不能用 openai 2.x）。

### 3.3 编译注意

若 `catkin_make` 报 CMakeCache 路径来自机器人 `/home/ari/...`：

```bash
cd /workspace/percy_ws && rm -rf build devel && catkin_make
```

---

## 4. 验证 TTS（有声再开对话）

```bash
source /workspace/percy_ws/devel/setup.bash
source /workspace/docker_ros1_noetic/env_ari.sh
export ARI_ROS_IP=10.68.0.130

rosrun percy_dialogue tts_test.py "Hello, can you hear me?"
```

- 日志应有 `Result: ... msg: ''`
- **人耳应听到机器人说话**

---

## 5. 没声音时：音量（重要）

### 5.1 ROS 参数（常不够）

```bash
rosparam get /pal/playback_volume    # 若为 0.0 会几乎无声
rosparam set /pal/playback_volume 0.8
rosparam set /pal/ttsVolume 1.0
```

### 5.2 PulseAudio（真正生效）

SSH 机器人（**在 `pal@ari-27c` 里执行**，不要在本机）。

**每次实验前推荐（默认 **60%**）：**

```bash
# 宿主机（推荐）
cd ~/Research && ./set_robot_volume.sh
# 或指定: ./set_robot_volume.sh 45
```

SSH 进机器人手动执行：

```bash
ssh pal@10.68.0.1

pactl set-default-sink output0
pactl set-sink-mute output0 0
pactl set-sink-volume output0 60%
pactl set-sink-mute pal-default-sink 0
pactl set-sink-volume pal-default-sink 60%
```

宿主机一行：

```bash
ssh pal@10.68.0.1 "pactl set-default-sink output0; pactl set-sink-mute output0 0; pactl set-sink-volume output0 60%; pactl set-sink-mute pal-default-sink 0; pactl set-sink-volume pal-default-sink 60%"
```

自检（应能从机器人胸前喇叭听到左右测试音）：

```bash
speaker-test -D pulse -t wav -c 2 -l 1
```

仍无声时再查：

```bash
pactl list sinks short
pactl list sinks | grep -A10 "Name: pal-default-sink"
```

若 **`pal-default-sink` 只有 ~1%** 或默认 sink 不是 `output0`，TTS 会几乎听不到；务必同时设 **`output0`** 与 **`pal-default-sink`**。太响：`./set_robot_volume.sh 45`；太轻：`./set_robot_volume.sh 70`。

说明：

- TTS 走 PAL 的 **`/tts` action**（[官方文档](https://docs.pal-robotics.com/sdk/23.12/actions/tts.html)）
- 机身喇叭在板载 **ALC897 Analog**，Pulse 里对应 **`output0`**；TTS 常经 **`pal-default-sink` → `output0`**
- 勿只用 `speaker-test` 默认设备（可能走 HDMI 无声）；用 **`-D pulse`** 且 **`set-default-sink output0`**
- 机器人重启后音量/默认 sink 可能复位，**每次实验前建议再执行上面几条 `pactl`**

---

## 6. 启动轮流对话（live_session）

### 6.0 延迟 / 拾音

**延迟顺序：** 你说完 → `end_silence_sec`（默认 0.8s）→ **Whisper** → **GPT** → **TTS** → `post_tts_mute_sec` 冷却。

| 现象 | 建议 |
|------|------|
| 每句都顶满 `max_utterance` | 降 `audio_gain` / Rode 硬件增益；环境安静；或 `rosservice call /percy_live/end_turn "{}"` |
| 小声听不见 | 略增 `audio_gain`（勿叠太高，易误触发 VAD） |
| 句内停顿被截断 | `end_silence_sec:=1.2` |
| 机器人回声当人声 | `post_tts_mute_sec:=1.5`～`2.0` |
| 环境声误触发 | `vad_mode:=3`（更不敏感） |

**默认：** `vad_backend=silero`、`audio_gain=2.0`、`end_silence_sec=0.8`、`max_utterance_sec=25`、`post_tts_mute_sec=1.0`。

### 6.1 对话 + stamp 对齐 A/V（推荐）

```bash
export PERCY_DATA_DIR=/workspace/percy_data
bash /workspace/record_dialogue_session.sh 18
```

产出 `percy_data/18/`：`audio.wav`、`whole_video.mp4`、`chat_history.json`、`dialogue_timeline.json`、`utterances/user_*.wav`、`session_events.jsonl` 等。

流程：

1. 等 **`Recording ->`** 与 **`Ready — speak`**
2. 对着外置麦说短句 → 停 **~0.8s** → 终端 **`You said:`** → 机器人回复
3. **Ctrl+C 一次** → `wait_finalize` + `benchmark_manifest.json`

录完离线 Whisper：`bash /workspace/percy_ws/src/percy/scripts/benchmark_asr.sh 18`

### 6.2 仅录制（无对话）

```bash
roslaunch percy record_aligned.launch session_id:=10
```

---

## 7. 常用 topic（检查用）

| Topic | 用途 |
|-------|------|
| `/audio/channel0` | 对话 / 录制默认麦 |
| `/head_front_camera/color/image_raw` | 头相机 raw（录制） |
| `/tts` | TTS action |
| `/tts/feedback` | 播完事件（`event_type: 8` = 一句结束） |

---

## 8. 故障速查

| 现象 | 处理 |
|------|------|
| `OPENAI_API_KEY not set` | 配置 `~/Research/.env.local`（见 §1）；容器内 `echo ${OPENAI_API_KEY:0:8}` 应有输出 |
| `No module named pal_interaction_msgs` | §3.1 clone + `CATKIN_IGNORE` + `catkin_make` |
| `No module named webrtcvad` / `openai` | 宿主机 `./ros1_ari.sh --rebuild` 或 `install_dialogue_deps.sh` |
| `live_session.launch` 找不到 | `cd /workspace/percy_ws && catkin_make && source devel/setup.bash` |
| TTS 成功但无声 | `./set_robot_volume.sh` 或 §5（`output0` + `pal-default-sink` 都调到 60%，勿只调一个） |
| `You said:` 是 YouTube/机器人自己的话 | 加大 `post_tts_mute_sec:=2.0`，等 Ready 再讲 |
| `rosparam` 在容器无效 | 命令要在 **Docker 内** 跑，不要在宿主机跑 `/workspace/...` |
| 容器里 `docker: command not found` | 已在容器内，不要嵌套 `docker run` |
| Ctrl+C 后打字不显示 | `bash /workspace/docker_ros1_noetic/fix_tty.sh` 或新开端口 |

---

## 9. 相关文件

| 路径 | 说明 |
|------|------|
| `experience/` | 本目录：Docker / 对话 / 录制 运维文档 |
| `percy_ws/src/percy_dialogue/` | 轮流对话 + 时间轴（独立包） |
| `percy_ws/src/percy_dialogue/launch/live_session.launch` | 对话 + A/V |
| `percy_ws/src/percy/` | stamp 对齐录制 + Whisper 离线 |
| `.env.local.example` | 环境变量模板 |
| `record_dialogue_session.sh` | 容器内一键（对话+A/V，推荐） |
| `docker_ros1_noetic/install_dialogue_deps.sh` | Python 依赖（旧镜像补装） |
| `docker_ros1_noetic/install_pal_msgs.sh` | 自动 clone + CATKIN_IGNORE（可选） |

---

## 10. 最短复制路径（日常）

```bash
# --- 宿主机 ---
ping -c 1 10.68.0.1
# 确保 ~/Research/.env.local 已配置 OPENAI_API_KEY

./set_robot_volume.sh

cd ~/Research && ./ros1_ari.sh
```

```bash
# --- Docker 内 ---
source /workspace/docker_ros1_noetic/env_ari.sh
export ARI_ROS_USE_LOOPBACK=0
export ARI_ROS_IP=10.68.0.130
source /workspace/percy_ws/devel/setup.bash
export PERCY_DATA_DIR=/workspace/percy_data

bash /workspace/record_dialogue_session.sh 18
# 机载麦: ... record_dialogue_session.sh 18 audio_source:=onboard
```
