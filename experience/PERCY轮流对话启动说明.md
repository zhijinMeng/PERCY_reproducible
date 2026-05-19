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
| **喇叭音量** | SSH 机器人：§5 一键脚本（默认 **30%**，含 `output0`） |

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
| `turn_dialogue` / `record_aligned` | 默认 `audio_source:=host_usb`，内含 `host_rode_capture` → `/audio/rode` |

**单终端对话**（无需再开 `host_rode_capture`）：

```bash
source /workspace/percy_ws/devel/setup.bash
source /workspace/docker_ros1_noetic/env_ari.sh
export ARI_ROS_IP=10.68.0.130
export PERCY_DATA_DIR=/workspace/percy_data

# 推荐（对话+A/V）：bash /workspace/record_dialogue_session.sh dialogue01

roslaunch percy_dialogue turn_dialogue.launch session_id:=dialogue01
# 旧版 turn_dialogue；推荐 live_session，见 PERCY实时对话与Benchmark采集说明.md
# 仍用机载麦: audio_source:=onboard
```

自检：`rostopic hz /audio/rode -w 3`；日志里 `host_rode_capture: device=plughw:X,0`。

若 `arecord` **Device busy**：宿主机关占用麦的程序；或 `roslaunch percy host_rode_capture.launch alsa_device:=plughw:N,0`。

**Rode 分步测试（先麦、再 A/V）**：

```bash
# 阶段 1：仅麦，不经 ROS（最快）
bash /workspace/record_host_mic_only.sh mic_test01 10
# 听 ~/Research/percy_data/mic_test01/audio.wav

# 阶段 1b：仅麦，走 ROS /audio/rode（可选）
roslaunch percy record_host_mic.launch session_id:=mic_ros01
# 对着麦说话 ~10s，Ctrl+C

# 阶段 2：麦 + 头相机 stamp 对齐
roslaunch percy record_aligned.launch session_id:=av_test01
```

诊断对比（注意 rosrun 只有两个参数：包名 + 脚本名）：

```bash
rosrun percy rode_capture_sanity.py --out-dir /tmp/rode_sanity
```

采集默认 **`capture_backend:=ffmpeg`**。直录 `record_host_mic_only.sh` 约 **-26 dBFS**；ROS 管道默认 **`gain:=3.0`** 与之接近。仍小声：`gain:=4.0`；过响：`gain:=2.0` 或调低 Rode 硬件增益。

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

**每次实验前推荐（约 30% 音量，现场可听、不刺耳）：**

```bash
ssh pal@10.68.0.1

pactl set-default-sink output0
pactl set-sink-mute output0 0
pactl set-sink-volume output0 30%
pactl set-sink-mute pal-default-sink 0
pactl set-sink-volume pal-default-sink 30%
```

宿主机一行：

```bash
ssh pal@10.68.0.1 "pactl set-default-sink output0; pactl set-sink-mute output0 0; pactl set-sink-volume output0 30%; pactl set-sink-mute pal-default-sink 0; pactl set-sink-volume pal-default-sink 30%"
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

若 **`pal-default-sink` 只有 ~1%** 或默认 sink 不是 `output0`，TTS 会几乎听不到；务必同时设 **`output0`** 与 **`pal-default-sink`**。太响可改为 `20%`，太轻可 `45%`。

说明：

- TTS 走 PAL 的 **`/tts` action**（[官方文档](https://docs.pal-robotics.com/sdk/23.12/actions/tts.html)）
- 机身喇叭在板载 **ALC897 Analog**，Pulse 里对应 **`output0`**；TTS 常经 **`pal-default-sink` → `output0`**
- 勿只用 `speaker-test` 默认设备（可能走 HDMI 无声）；用 **`-D pulse`** 且 **`set-default-sink output0`**
- 机器人重启后音量/默认 sink 可能复位，**每次实验前建议再执行上面几条 `pactl`**

---

## 6. 启动轮流对话

### 6.0 延迟 / 拾音（小声听不见、要等很久）

**延迟从哪来（大致顺序）：** 你说完 → `end_silence_sec` 等静音 → 上传 **Whisper** → **GPT** → **TTS 播放** → `post_tts_mute_sec` 冷却。网络 API 占大头；launch 里能调的是前几段等待。

| 现象 | 建议参数 |
|------|----------|
| 必须大喊、小声听不见 | `vad_mode:=0`（**更灵敏**，数字越小越敏感）、`audio_gain:=3.0` |
| 整体太慢 | `end_silence_sec:=0.9`、`min_whisper_sec:=0.6`、`post_tts_mute_sec:=1.0` |
| 句内停顿被截断 | 加大 `end_silence_sec:=1.3`（会略增延迟） |
| 机器人回声当人声 | `post_tts_mute_sec:=1.5`，`vad_mode:=1` |
| 杂音 / 幻听 `you` 变多 | `vad_mode:=1`、`audio_gain:=2.5` |
| 稳定底噪（空调/风扇） | 默认 `enable_noise_reduce:=true`；启动后安静 2–3s 让节点学噪声谱 |
| 人声被削薄 | `noise_prop_decrease:=0.7`（默认 0.85，越大削噪越强） |

**默认（launch 已改）：** `vad_mode=0`、`audio_gain=2.8`、`end_silence_sec=1.0`、`min_whisper_sec=0.7`、`post_tts_mute_sec=1.2`。

更激进（小声 + 更快，环境要相对安静）：

```bash
roslaunch percy_dialogue turn_dialogue.launch session_id:=dialogue01 \
  vad_mode:=0 audio_gain:=3.0 \
  end_silence_sec:=0.9 min_whisper_sec:=0.6 post_tts_mute_sec:=1.0 \
  enable_vader:=false
```

### 6.1 只对话、不录 A/V（调试，**无** audio.wav / whole_video.mp4）

```bash
roslaunch percy_dialogue turn_dialogue.launch session_id:=dialogue01
```

仅产出 `chat_history.json`、`dialogue_timeline.json`（时间轴可能为 `dialogue_fallback_ros_now`）。

### 6.2 对话 + stamp 对齐 A/V（**最终落盘，推荐**）

**一条命令**同时写录制与对话日志（外置 Rode 默认 `/audio/rode`）：

```bash
# 容器内（已 source percy_ws + env_ari）
export PERCY_DATA_DIR=/workspace/percy_data
bash /workspace/record_dialogue_session.sh 16
```

或：

```bash
roslaunch percy_dialogue benchmark_session.launch session_id:=16
```

产出 `~/Research/percy_data/16/`：

| 文件 | 说明 |
|------|------|
| `audio.wav`, `whole_video.mp4` | stamp 对齐录制（与 session 15 同链路） |
| `recording_meta.json`, `finalize.done` | 元数据 / 转码完成 |
| `chat_history.json`, `dialogue_timeline.json` | 对话日志（`t_*_sec` 对齐 `recording_meta`） |
| `utterance_*.wav` | 每句送 Whisper 前的切片 |
| `benchmark_manifest.json` | `record_dialogue_session.sh` 结束后可选生成 |

**Ctrl+C 一次** → 停对话 + 录制 → 自动 `wait_finalize`。

流程：

1. 等日志 **`Recording ->`**（约 2s 后对话启动）  
2. 机器人问候 → **`Ready for your next turn.`** 后说话  
3. 说完停 **~0.65s**（`energy` 端点）  
4. 看 `Whisper` / `You said:` → 机器人回复  

录完 ASR：`bash /workspace/benchmark_asr.sh 16`（见录制说明）。

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
| `turn_dialogue.launch` 找不到 | `source /workspace/percy_ws/devel/setup.bash` |
| `No module named attention_manager` | 正常：`turn_dialogue.launch` 默认不启 `robot_head` |
| TTS 成功但无声 | §5：`set-default-sink output0` + `output0` / `pal-default-sink` 调到 30%（勿只调一个） |
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
| `percy_ws/src/percy_dialogue/launch/benchmark_session.launch` | 录制 + 对话 |
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

ssh pal@10.68.0.1 "pactl set-default-sink output0; pactl set-sink-mute output0 0; pactl set-sink-volume output0 30%; pactl set-sink-mute pal-default-sink 0; pactl set-sink-volume pal-default-sink 30%"

cd ~/Research && ./ros1_ari.sh
```

```bash
# --- Docker 内 ---
source /workspace/docker_ros1_noetic/env_ari.sh
export ARI_ROS_USE_LOOPBACK=0
export ARI_ROS_IP=10.68.0.130
source /workspace/percy_ws/devel/setup.bash
export PERCY_DATA_DIR=/workspace/percy_data

bash /workspace/record_dialogue_session.sh 16
# 仅对话无 A/V: roslaunch percy_dialogue turn_dialogue.launch session_id:=x
# 机载麦: roslaunch percy_dialogue benchmark_session.launch session_id:=x audio_source:=onboard
```
