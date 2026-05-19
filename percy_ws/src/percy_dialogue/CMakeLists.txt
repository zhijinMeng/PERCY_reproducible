cmake_minimum_required(VERSION 3.0.2)
project(percy_dialogue)

find_package(catkin REQUIRED COMPONENTS
  rospy
  std_msgs
  audio_common_msgs
  actionlib
  pal_interaction_msgs
)

catkin_package(
  CATKIN_DEPENDS rospy std_msgs audio_common_msgs actionlib pal_interaction_msgs
)

# session_timeline.py 仅作模块，勿 catkin_install_python（会进 devel/lib 遮蔽 import）
catkin_install_python(PROGRAMS
  scripts/turn_dialogue.py
  scripts/tts_test.py
  scripts/build_benchmark_manifest.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(DIRECTORY launch
  DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION}
  FILES_MATCHING PATTERN "*.launch"
)
