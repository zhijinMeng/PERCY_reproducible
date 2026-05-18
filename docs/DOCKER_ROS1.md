# Docker 里的 ROS1 与 ARI 机器人如何联动

本文说明：为什么用 Docker、它和机器人之间**没有特殊协议**、以及**每次新开终端**如何一步步连上机器人并跑 `percy_ws`。

---

## 1. Docker 在这里扮演什么角色？

可以把 Docker 想成：在你笔记本里再跑一个**轻量的 Linux 环境**（这里是带 **ROS Noetic** 的 Ubuntu 20.04 风格镜像），和宿主机系统（例如 Ubuntu 22.04 + **ROS2 Humble**）**隔离**。

- **宿主机**：继续用你的 ROS2、`percy_ros2_ws`、日常软件。
- **容器里**：只装 **ROS1**，用来和 **只提供 ROS1 的 ARI** 说话（`rostopic`、`roslaunch` 等）。

Docker **不负责**「发现机器人」；它只是给你一套**能执行 ROS1 命令的环境**。

---

## 2. 和机器人是怎么「联动」的？（核心就三件事）

联动本质是 **TCP/IP 上的 ROS1 主从架构**，和是否在 Docker 里**无关**。

### （1）机器人上跑着 roscore（ROS master）

- 一般监听 **`10.68.0.1:11311`**（你当前网段里机器人常是 `.1`）。
- 所有传感器、控制节点在机器人上**向这个 master 注册**，topic 列表你 SSH 上去 `rostopic list` 能看到。

### （2）你的笔记本和机器人在同一局域网

- 例如网线：`笔记本 10.68.0.x` ↔ `机器人 10.68.0.1`。
- 能 `ping 10.68.0.1` 是前提。

### （3）在「跑 ROS1 的那一侧」设置环境变量

在 **Docker 容器内的 shell** 里：

- **`ROS_MASTER_URI=http://10.68.0.1:11311`**  
  告诉 ROS1：**不要连本机 localhost**，去连**机器人上的 master**。
- **`ROS_IP=你笔记本在 10.68.0.x 的地址`**（例如 `10.68.0.128`）  
  告诉网络上其他节点：**回连我时用这个 IP**。笔记本若有多张网卡（WiFi + 网线），这一步很重要。

设置好之后，`rostopic list` 就会列出**机器人上**的 topic，就像你在机器人里执行一样——只是**进程跑在笔记本的 Docker 里**，**数据通过网线/WiFi 从机器人过来**。

### 为什么脚本里用 `--net=host`？

`run_ros1_noetic.sh` 里 Docker 使用了 **`--network host`**，表示：**容器和宿主机共用同一张「网络栈」**（IP、路由、端口与笔记本一致）。这样：

- 容器里访问 `10.68.0.1` 和你在宿主机 `ping` 一样；
- 不必再做一层 Docker 端口映射，对 ROS1 这种 **11311 + 动态端口** 更省事。

---

## 3. 常见误解

| 误解 | 实际情况 |
|------|------------|
| Docker 会自动找到机器人 | 不会。要靠 **`ROS_MASTER_URI`** 指到机器人 IP。 |
| 容器里必须再 `roscore` | **连 ARI 时不要**在笔记本再开 `roscore`，否则占 11311，和「连远程 master」冲突。 |
| ROS2 和 ROS1 在 Docker 里自动互通 | **不会**。ROS2 在宿主机、ROS1 在容器，是两套进程；要用桥、或各自订阅/自己的话题，或中间用非 ROS 协议传数据。 |

---

## 4. 下次新开一个 Terminal：从进 Docker 到连机器人（推荐顺序）

以下路径按你当前仓库布局：项目根目录为 **`~/Research`**，Docker 脚本在 **`~/Research/docker_ros1_noetic/`**。

### 步骤 A：宿主机开一个终端

```bash
cd ~/Research
./docker_ros1_noetic/run_ros1_noetic.sh
```

首次运行会 **自动 `docker build`** 本地镜像 `research/ros1-noetic-percy:local`（在官方 Noetic 桌面镜像基础上安装了 **`ros-noetic-audio-common-msgs`**，否则 `percy_ws` 无法 `catkin_make`）。  
若需强制重建镜像：`./docker_ros1_noetic/run_ros1_noetic.sh --rebuild`

进入容器后，提示符类似 `root@...:/workspace#`。  
`/workspace` 对应你宿主机上的 **`~/Research`**（已挂载）。

### 步骤 B：在容器里加载 ROS1 与 ARI 环境

容器启动脚本里已经执行过 `source /opt/ros/noetic/setup.bash`。  
**每次新开容器或新 shell**，再执行：

```bash
source /workspace/docker_ros1_noetic/env_ari.sh
```

确认：

```bash
echo $ROS_MASTER_URI
# 应为 http://10.68.0.1:11311（若机器人 IP 变了，改 env_ari.sh 或见下文「自定义 IP」）
```

自检话题：

```bash
rostopic list | head -30
```

若只有 `/rosout`，说明仍连在 **localhost** 的 master：再执行一次上面的 `env_ari.sh`，或检查 `env_ari.sh` 是否已保存为**强制指向机器人**的版本。

### 步骤 C：（首次或改过代码后）编译并加载 `percy_ws`

**建议在容器内编译**，这样 `devel/setup.bash` 里的路径是 `/workspace/percy_ws/...`，与挂载一致。

若出现 **`devel/setup.bash: No such file`**，说明还没成功编过：在容器内执行

```bash
cd /workspace/percy_ws
catkin_make
```

若 CMake 报缺少 **`audio_common_msgs`**，请使用更新后的 **`run_ros1_noetic.sh`**（会自动构建带依赖的本地镜像），或手动：`apt-get update && apt-get install -y ros-noetic-audio-common-msgs` 后再 `catkin_make`。

日常进入容器后：

```bash
source devel/setup.bash
```

### 步骤 D：录制（示例）

```bash
export PERCY_DATA_DIR=/workspace/percy_data
mkdir -p "$PERCY_DATA_DIR"
roslaunch percy record_aligned.launch session_id:=试跑01
```

录制的文件在容器内路径 `/workspace/percy_data/...`，对应宿主机 **`~/Research/percy_data/...`**。

### 退出容器

`exit` 或 `Ctrl+D`。容器一般用 `--rm`，退出即删除；**下次重新从步骤 A 进来**即可。

---

## 5. 自定义机器人 IP / 本机 IP

编辑 **`~/Research/docker_ros1_noetic/env_ari.sh`** 里的默认地址；或在 `source` 之前临时指定：

```bash
export ARI_ROS_MASTER_URI=http://10.68.0.1:11311
export ARI_ROS_IP=10.68.0.128
source /workspace/docker_ros1_noetic/env_ari.sh
```

---

## 6. 和 ROS2 笔记本的关系（备忘）

- **Docker 里的 ROS1**：连机器人、录 bag、跑 `percy_ws` 里 ROS1 节点。
- **宿主机 ROS2**：继续开发 `percy_ros2_ws`；与 ROS1 **不自动互通**，需要以后自行设计桥接或离线处理。

---

## 7. 故障速查

| 现象 | 可检查项 |
|------|-----------|
| `rostopic list` 只有 `/rosout` | `echo ROS_MASTER_URI` 是否为 `http://10.68.0.1:11311`；是否误在本机起了 `roscore` |
| 连不上 master | `ping 10.68.0.1`；机器人是否开机、roscore 是否在跑 |
| `rostopic list \| head` 末尾 Broken pipe 提示 | 正常，可忽略，或不用管道 |

---

*文档随仓库路径 `Research/docker_ros1_noetic/` 与 `Research/percy_ws/` 更新；若你移动了目录，请相应改脚本中的路径。*
