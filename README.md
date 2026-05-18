# PERCY_reproducible

Robot-side deployment bundle: timestamp-aligned A/V recording (`percy`) + LLM dialogue stack (`gpt_server`, `chatting_system`).

## Layout

- `percy_ws/` — Catkin workspace with `percy` (stamp-aligned recorder, H.264 post-process)
- `PERCY/` — Catkin workspace with dialogue / GPT packages

## On the ARI robot (Ubuntu 20.04 + ROS Noetic)

```bash
git clone git@github.com:zhijinMeng/PERCY_reproducible.git
cd PERCY_reproducible

sudo apt-get update
sudo apt-get install -y ffmpeg ros-noetic-audio-common-msgs python3-pip python3-opencv

pip3 install openai pandas

# Build recording workspace
cd percy_ws && catkin_make && source devel/setup.bash

# Build PERCY stack (separate terminal or after)
cd ../PERCY && catkin_make && source devel/setup.bash

export PERCY_DATA_DIR=~/percy_data
mkdir -p "$PERCY_DATA_DIR"
export OPENAI_API_KEY="your-key"

# Record (uses robot topics at full rate)
roslaunch percy record_aligned.launch session_id:=0

# LLM + dialogue (see PERCY/src/chatting_system/launch/start.launch)
roslaunch chatting_system start.launch id:=0
```

Use `ROS_MASTER_URI=http://localhost:11311` when running entirely on the robot.

## Laptop + Docker (optional)

See `docs/DOCKER_ROS1.md` and `docker/` if you still record over WiFi from a laptop.
