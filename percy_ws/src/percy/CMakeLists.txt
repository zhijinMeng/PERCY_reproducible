cmake_minimum_required(VERSION 3.0.2)
project(percy)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  sensor_msgs
  cv_bridge
  audio_common_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs sensor_msgs cv_bridge audio_common_msgs
)

catkin_install_python(PROGRAMS
  scripts/stamp_aligned_recorder.py
  scripts/finalize_recording.py
  scripts/benchmark_whisper_align.py
  scripts/audio_channel_probe.py
  scripts/extract_noise_profile.py
  scripts/host_rode_capture.py
  scripts/host_usb_mic_detect.py
  scripts/rode_capture_sanity.py
  scripts/host_mic_wav_recorder.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
  FILES_MATCHING PATTERN "*.launch"
)

install(PROGRAMS scripts/wait_finalize.sh
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(PROGRAMS scripts/benchmark_asr.sh
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
