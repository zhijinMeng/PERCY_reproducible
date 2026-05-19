# Research — PERCY / ARI benchmark

ARI 机器人 + Docker ROS1 下的 **stamp 对齐录制**（`percy`）与 **轮流对话**（`percy_dialogue`）。

| 路径 | 说明 |
|------|------|
| [`percy_ws/`](percy_ws/) | Catkin 工作区（`percy`、`percy_dialogue`、`pal_msgs`） |
| [`experience/`](experience/) | 现场运维文档（Docker、对话、录制） |
| [`docker_ros1_noetic/`](docker_ros1_noetic/) | 容器脚本与依赖安装 |
| `ros1_ari.sh` | 进 Docker |
| `record_dialogue_session.sh` | 录制 + 对话一键 |

配置：复制 `.env.local.example` → `.env.local`，填入 `OPENAI_API_KEY`。

快速上手：[`experience/PERCY轮流对话启动说明.md`](experience/PERCY轮流对话启动说明.md)
