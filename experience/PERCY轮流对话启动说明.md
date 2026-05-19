# PERCY 轮流对话启动说明（ARI + Docker）

在笔记本 Docker 里连机器人，用 **onboard 麦** `/audio/channel0` 做 **你说一句 → 机器人回一句**。  
录制 benchmark 仍用 [`录制对齐音视频说明.md`](录制对齐音视频说明.md)，与此分开。

更完整的网线 / Docker 见 [`DOCKER_ROS1_连机器人说明.md`](DOCKER_ROS1_连机器人说明.md)。

---

## 0. 每次实验前速查

| 检查项 | 命令 / 期望 |
|--------|-------------|
| 网线千兆 | 宿主机 `ethtool enp3s0 \| grep Speed` → **1000Mb/s** |
| 机器人通 | `ping -c 2 10.68.0.1` |
| 本机 IP | `ip -4 addr show enp3s0`（例 **10.68.0.130**） |
| 音频 | Docker 内 `rostopic hz /audio/channel0 -w 5` 有数据 |
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
./ros1_ari.sh
```

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

### 6.1 只对话、不录视频（调试）

```bash
export PERCY_DATA_DIR=/workspace/percy_data

roslaunch percy_dialogue turn_dialogue.launch \
  session_id:=dialogue01 \
  post_tts_mute_sec:=1.5
```

### 6.2 对话 + 对齐录制（推荐，期刊数据）

`percy_dialogue/benchmark_session.launch`：**`percy` 录制 + `turn_dialogue`**，对话带 **`dialogue_timeline.json`** 时间轴：

```bash
export PERCY_DATA_DIR=/workspace/percy_data

cd /workspace
./record_dialogue_session.sh 13
```

产出 `percy_data/13/`：

| 文件 | 来源 |
|------|------|
| `audio.wav`, `whole_video.mp4`, `recording_meta.json` | 对齐录制 |
| `chat_history.json`, `dialogue_timeline.json`, `utterance_*.wav` | 轮流对话（相对录制起点的 `t_*_sec`） |

**Ctrl+C 一次**结束对话 → 脚本自动停录制并 `wait_finalize`。  
录完可跑：`./benchmark_asr.sh 13`（见录制说明）。

流程：

1. 机器人英文问候  
2. 日志 **`Ready for your next turn.`** 后再说话  
3. 说完停顿约 **1 秒**（`end_silence_sec`）  
4. TTS 播完后 **1.5s** 冷却再听（减轻回声被当成用户说话）

记录：`~/Research/percy_data/dialogue01/chat_history.json`

### 宿主机一键

```bash
cd ~/Research
./run_turn_dialogue.sh dialogue01
```

（脚本会读 `.env.local`）

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
| `run_turn_dialogue.sh` | 宿主机一键 |
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

roslaunch percy_dialogue turn_dialogue.launch session_id:=dialogue01 post_tts_mute_sec:=1.5
```
