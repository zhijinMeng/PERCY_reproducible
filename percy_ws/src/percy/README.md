# percy — stamp 对齐音视频录制

**对话与时间轴**已抽到独立包 **`percy_dialogue`**，本包只负责录制与离线 ASR。

## 依赖

- ROS Noetic，`audio_common_msgs`，`cv_bridge`
- 可选联合实验：`percy_dialogue` + `OPENAI_API_KEY`

## 编译

```bash
cd ~/Research/percy_ws && catkin_make && source devel/setup.bash
```

## Launch

```bash
roslaunch percy record_aligned.launch session_id:=13
```

对话或「录制+对话」见 **`percy_dialogue`**：

```bash
roslaunch percy_dialogue benchmark_session.launch session_id:=13
```

## Session 产出

| 文件 | 说明 |
|------|------|
| `audio.wav` / `whole_video.mp4` | 对齐 A/V |
| `recording_meta.json` | 含 `first_image_stamp`（时间原点） |
| `audio_whisper_large_v3.json` | 离线 Whisper |

## 离线

```bash
rosrun percy benchmark_asr.sh ~/Research/percy_data/13
```

宿主机一键录制+对话：`~/Research/record_dialogue_session.sh 13`

录制步骤与检查：[`~/Research/experience/录制对齐音视频说明.md`](../../../experience/录制对齐音视频说明.md)
