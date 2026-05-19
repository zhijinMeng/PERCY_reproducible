# Docker ROS1 网线连 ARI 机器人

在宿主机 **`~/Research`** 用 Docker 跑 ROS1，通过**网线**连机器人上的 roscore。数据走局域网 TCP，和是否在 Docker 里无关。

---

## 1. 网线怎么接

| 项目 | 说明 |
|------|------|
| 推荐插法 | 机器人 ↔ **笔记本板载网口 `enp3s0`**（优先，易协商千兆） |
| 慎用 | 扩展坞 USB 网口、劣质转接头（易掉到 **100M / 10M**，raw 相机帧率会崩） |
| 做实验时 | 可拔掉另一根校园网/USB 网卡，避免路由混乱 |
| 机器人侧 | 常见对外口 **`eth0`**，与笔记本同网段 **`10.68.0.0/24`** |

### 插好后在宿主机检查（必做）

```bash
# 应看到 Link detected: yes；做 raw 相机建议 Speed: 1000Mb/s
ethtool enp3s0 | grep -E 'Speed|Link detected'

# 去机器人应走 enp3s0
ip route get 10.68.0.1

ping -c 2 10.68.0.1
```

| 协商速率 | head `image_raw` 大致帧率 |
|----------|---------------------------|
| **1000 Mb/s** | ~**30** fps |
| 100 Mb/s | ~12–13 fps |
| **10 Mb/s** | ~**1.3** fps（几乎不可用） |

---

## 2. 地址与端口

| 角色 | IP（示例） | 端口 / 用途 |
|------|------------|-------------|
| 机器人 roscore | **`10.68.0.1`** | **11311**（`ROS_MASTER_URI`） |
| 笔记本（网线） | **`10.68.0.130`**（以 `ip addr` 为准） | ROS 节点回连用 `ROS_IP` |
| SSH 机器人 | `pal@10.68.0.1` 或 `pal@ari-27c` | **22** |
| 机器人主机名 | `ari-27c` | Publisher 常登记此名；`ros1_ari.sh` 会 `--add-host` |

环境变量（容器内由 `env_ari.sh` 设置）：

| 变量 | 默认值 |
|------|--------|
| `ROS_MASTER_URI` | `http://10.68.0.1:11311` |
| `ROS_IP` | 网线本机 IP（如 `10.68.0.130`）；Docker 内可 `ARI_ROS_USE_LOOPBACK=0` 显式指定 |

---

## 3. 从 `~/Research` 进 Docker 并连机器人

### 3.1 宿主机（一条命令进容器）

```bash
cd ~/Research

# 推荐：进容器并自动连机器人（等价于 run_ros1_noetic.sh --ari）
export ARI_ROS_IP=10.68.0.130          # 改成你笔记本在 10.68.0.x 的地址
export ARI_ROS_USE_LOOPBACK=0
./ros1_ari.sh
```

首次会 build 镜像 `research/ros1-noetic-percy:local`。强制重建：`./ros1_ari.sh --rebuild`

容器内工作目录：**`/workspace`** = 宿主机 **`~/Research`**

### 3.2 容器内（每个新 shell 若未自动 source）

```bash
source /opt/ros/noetic/setup.bash
source /workspace/docker_ros1_noetic/env_ari.sh
source /workspace/percy_ws/devel/setup.bash   # 跑 percy 时需要

echo $ROS_MASTER_URI    # http://10.68.0.1:11311
echo $ROS_IP            # 应为 10.68.0.x，不是 127.0.0.1（除非你刻意用 loopback）
```

### 3.3 连接自检

```bash
rostopic list | head -20          # 应有很多机器人 topic，不能只有 /rosout
rostopic info /head_front_camera/color/image_raw   # Publishers 不能是 None
```

**不要在笔记本上再开 `roscore`**，否则会占 11311 或连错 master。

### 3.4 轮流对话 Python 依赖（`percy_dialogue`）

**推荐（一次构建，以后每个新容器都有）：** 镜像 `research/ros1-noetic-percy:local` 的 Dockerfile 已内置  
`openai`、`webrtcvad`、`nltk`/VADER。更新依赖后或首次使用，在**宿主机**重建镜像一次：

```bash
cd ~/Research
./ros1_ari.sh --rebuild
```

构建日志末尾应有 `image deps ok: openai 1.14.1`。之后每次 `./ros1_ari.sh` 进新容器**不必**再装 pip 包。

进容器可快速自检：

```bash
python3 -c "import webrtcvad, openai; from nltk.sentiment.vader import SentimentIntensityAnalyzer; print('deps OK')"
```

**仅当**仍报 `No module named webrtcvad`（旧镜像未 rebuild）时，在容器内补装：

```bash
bash /workspace/docker_ros1_noetic/install_dialogue_deps.sh
```

对话还需 **OpenAI API Key**（不必每次 `export`）：

```bash
cd ~/Research
cp .env.local.example .env.local    # 只需做一次
# 编辑 .env.local，填入 OPENAI_API_KEY=（你的真实密钥）
./ros1_ari.sh                       # 自动读 .env.local 并传入容器
```

容器内可验证：`echo ${OPENAI_API_KEY:0:8}`（应有非空输出，且不是文档示例里的假字符串）。

更完整的 launch / TTS / 调参见 [`PERCY轮流对话启动说明.md`](PERCY轮流对话启动说明.md)。

---

## 4. `rostopic` 常用命令

把下面的 **`TOPIC`** 换成第 5 节里的名字。

```bash
# 列表
rostopic list
rostopic list | grep -E 'head_front|torso_front|audio'

# 是否在发、帧率
rostopic info TOPIC
rostopic hz TOPIC

# 带宽（raw 相机约 0.92MB/帧 × fps）
rostopic bw TOPIC

# 看一帧元数据（别对 raw 长时间 echo 全图）
rostopic echo TOPIC -n 1 | grep -E 'width|height|encoding'

# 消息类型
rostopic type TOPIC
```

### 录前快速检查（推荐）

```bash
ethtool enp3s0 | grep Speed    # 宿主机另开终端
rostopic hz /head_front_camera/color/image_raw
rostopic hz /audio/channel0
```

---

## 5. 常用 Topic 名称

### 5.1 头部相机（默认录制）

| Topic | 类型 | 说明 |
|-------|------|------|
| `/head_front_camera/color/image_raw` | `sensor_msgs/Image` | **640×480 rgb8**，千兆网线笔记本约 **30 Hz**；**录制与 emotion 均用此 topic** |
| `/head_front_camera/color/camera_info` | `sensor_msgs/CameraInfo` | 内参 |

### 5.2 胸部相机（备用）

| Topic | 类型 | 说明 |
|-------|------|------|
| `/torso_front_camera/color/image_raw` | `sensor_msgs/Image` | 常见 **848×480**；未启动时 `hz` 无数据 |
| `/torso_back_camera/fisheye1/image_raw` | `sensor_msgs/Image` | 背部鱼眼 |
| `/torso_back_camera/fisheye2/image_raw` | `sensor_msgs/Image` | 背部鱼眼 |

### 5.3 音频（ReSpeaker）

| Topic | 说明 |
|-------|------|
| **`/audio/channel0`** | **默认录制**；与 `/audio/raw` 相同；对话/ASR 用人声敏感 |
| `/audio/channel1` … `/audio/channel4` | 单麦，通常更安静、人声更小 |
| `/audio/channel5` | 常无声 |
| `/audio/speech` | VAD 门控，稀疏，**不适合**连续对齐录制 |
| `/audio/raw` | 同 channel0 |

### 5.4 深度与其它（按需）

| Topic |
|-------|
| `/head_front_camera/depth/image_rect_raw` |
| `/head_front_camera/depth/color/points` |
| `/camera/color/image_raw` |

---

## 6. 录制对齐音视频

**详细步骤见：[`录制对齐音视频说明.md`](录制对齐音视频说明.md)**（复制即用命令、录完检查、故障表）。

```bash
source /workspace/docker_ros1_noetic/env_ari.sh
source /workspace/percy_ws/devel/setup.bash
export PERCY_DATA_DIR=/workspace/percy_data
./record_aligned.sh 7    # Ctrl+C 后自动等待 finalize，见 录制对齐音视频说明.md
```

---

## 7. 机器人本机录（满帧、无网线带宽问题）

```bash
ssh pal@10.68.0.1
source /opt/ros/noetic/setup.bash
cd ~/zhijinmeng/PERCY_reproducible/percy_ws && source devel/setup.bash
export PERCY_DATA_DIR=~/zhijinmeng/percy_data
roslaunch percy record_aligned.launch session_id:=7
```

拷回笔记本：

```bash
scp -r pal@10.68.0.1:~/zhijinmeng/percy_data/7 ~/Research/percy_data/
```

---

## 8. 同步代码到机器人

```bash
rsync -avz ~/Research/PERCY_reproducible/ pal@ari-27c:~/zhijinmeng/PERCY_reproducible/
```

---

## 9. 故障速查

| 现象 | 处理 |
|------|------|
| `rostopic list` 只有 `/rosout` | 再 `source env_ari.sh`；确认 `ROS_MASTER_URI` 指向 `10.68.0.1:11311` |
| `Publishers: None` | 机器人上相机节点未起，SSH 查 `rosnode list \| grep camera` |
| head `image_raw` **~1 fps** | `ethtool enp3s0` 是否为 **10Mb/s**；换线、直插板载网口、别用慢 Dock |
| head `image_raw` **~13 fps** | 百兆上限；换千兆线/口 |
| head `image_raw` **no new messages** | 机器人头相机未发布（`rostopic info` 里 **Publishers: None**），与网线无关时需 SSH 重启头相机 |
| `roslaunch` 报 Unable to contact my own server | `export ARI_ROS_USE_LOOPBACK=0` 且 `export ARI_ROS_IP=10.68.0.x` 后重进容器 |
| `No module named webrtcvad` / `openai` | 宿主机 `./ros1_ari.sh --rebuild`；或容器内 `install_dialogue_deps.sh`（见 §3.4） |
| `OPENAI_API_KEY not set` | 配置 `~/Research/.env.local`（见 §3.4）；检查是否误 `export` 了文档示例文字 |
| 音画时长差很多 | 看 `recording_meta.json` 的 `video_fix_timeline`；session 2 类问题多为当时 **2fps WiFi** |

---

## 10. 自定义 IP

编辑 `~/Research/docker_ros1_noetic/env_ari.sh`，或进容器前：

```bash
export ARI_ROS_MASTER_URI=http://10.68.0.1:11311
export ARI_ROS_IP=10.68.0.130
export ARI_ROS_USE_LOOPBACK=0
./ros1_ari.sh
```

---

*路径：`~/Research/experience/DOCKER_ROS1_连机器人说明.md` · 脚本：`ros1_ari.sh`、`docker_ros1_noetic/env_ari.sh`、`docker_ros1_noetic/install_dialogue_deps.sh`、`percy_ws`（`percy` / `percy_dialogue`）*
