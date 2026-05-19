# PERCY 实时对话 + Benchmark 采集（推荐流程）

笔记本 Docker 连 ARI 机器人：**外置 USB 麦** + **头相机 raw 图**，一边实时轮流对话，一边落盘对齐的音视频与对话日志。

相关文档：

| 文档 | 用途 |
|------|------|
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

## 3. 一键采集（对话 + A/V）

### 3.1 启动

```bash
# 宿主机
cd ~/Research
./ros1_ari.sh

# 容器内（已 source devel + env_ari）
bash /workspace/record_dialogue_session.sh 18
```

### 3.2 使用流程

1. 日志出现 `Recording -> ... (t0=...)` 与 `Session t0 from /percy/session/t0`
2. 机器人问候 → **`Ready — speak (pause ~0.8s to end turn)`**
3. **对着外置麦**说一两句 → 停顿约 **0.8s** → 终端 `You said:` → 机器人回复
4. 重复多轮；结束：**Ctrl+C 一次**（会 wait_finalize + 写 manifest）

### 3.3 手动截句（可选）

说完不想等静音：

```bash
rosservice call /percy_live/end_turn "{}"
```

### 3.4 常用参数

```bash
bash /workspace/record_dialogue_session.sh 18 \
  end_silence_sec:=1.0 \
  post_tts_mute_sec:=1.5 \
  vad_mode:=3 \
  max_utterance_sec:=25.0
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `vad_mode` | 3 | WebRTC 灵敏度（3 较不敏感，少误触发） |
| `end_silence_sec` | 0.8 | 静音多久判定一句结束 |
| `post_tts_mute_sec` | 1.2 | TTS 后冷却，防机器人回声 |
| `max_utterance_sec` | 25 | 最长一句，超时强制送 ASR（兜底；正常靠静音截断） |

---

## 4. 产出目录结构

`~/Research/percy_data/<session_id>/`（容器内 `/workspace/percy_data/...`）：

```
<session_id>/
├── audio.wav                 # 整段外置麦，与视频 stamp 对齐
├── whole_video.mp4           # 头相机 H.264（无内嵌音轨）
├── recording_meta.json
├── finalize.done
├── chat_history.json         # 对话文本
├── dialogue_timeline.json    # 带 t_start_sec / t_end_sec（相对 t0）
├── session_events.jsonl      # 调试事件
├── benchmark_manifest.json   # 脚本结束后自动生成
└── utterances/               # 用户每轮语音切片
    ├── user_0001.wav
    └── ...
```

时间轴 **t=0** = 录制开始时的笔记本 `rospy.Time`（话题 `/percy/session/t0`），与 `audio.wav` 起点一致。

---

## 5. 仅录制（无对话）

```bash
roslaunch percy record_aligned.launch session_id:=N
# 或: bash /workspace/record_aligned.sh N
```

对话 + A/V 仍用 **`record_dialogue_session.sh`**。

---

## 6. 打包发给导师

```bash
cd ~/Research
zip -r -9 percy_session_17.zip percy_data/17 -x "percy_data/17/finalize.log"
# 或
cd ~/Research/percy_data
tar -czf percy_session_17.tar.gz --exclude="17/finalize.log" 17
```

大文件是 `whole_video.mp4` 与 `audio.wav`；切片在 `utterances/`。

---

## 7. 常见问题

| 现象 | 处理 |
|------|------|
| 机器人不回应 | 等 `Ready` 再说话；看是否 `You said:`；查 `OPENAI_API_KEY` |
| 每句都顶满 `max_utterance` | 底噪/增益过高，VAD 判不停；降 `audio_gain` / Rode 增益，或 `rosservice call /percy_live/end_turn "{}"` |
| `Connection error` / DNS | 宿主机 `ping api.openai.com`；节点会自动重试 3 次 |
| 无 `/audio/rode` | 宿主机重进 `./ros1_ari.sh`（带 USB 麦）；`arecord -l` 见 NTUSB |
| 视频未 H.264 / 未 finalize | Ctrl+C 后跑 `bash .../wait_finalize.sh /workspace/percy_data/N` |
| `catkin_make` 失败 `std_srvs` | 已写在 `package.xml`；重新 `catkin_make` |
| 目录权限 root | Docker 录制属 root；整理/压缩可在容器内 `docker exec` 执行 |

---

## 8. 代码入口速查

| 路径 | 说明 |
|------|------|
| `record_dialogue_session.sh` | 宿主机/容器一键脚本 |
| `percy_ws/.../launch/live_session.launch` | 推荐 launch |
| `percy_ws/.../scripts/live_dialogue.py` | 实时对话 |
| `percy_ws/.../scripts/stamp_aligned_recorder.py` | A/V 对齐录制 |
| `percy_ws/.../scripts/host_rode_capture.py` | 外置麦 → `/audio/rode` |
| `percy_ws/.../scripts/test_vad_eou.py` | 离线回放 VAD 截断 |

路径根目录：`~/Research`（容器 `/workspace`）。
