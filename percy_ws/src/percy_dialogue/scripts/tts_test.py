#!/usr/bin/env python3
"""Send one /tts goal (PAL). Usage: rosrun percy_dialogue tts_test.py [text]"""
import sys

import actionlib
import rospy
from pal_interaction_msgs.msg import TtsAction, TtsGoal


def main():
    rospy.init_node("tts_test")
    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Hello. This is a TTS test."
    lang = rospy.get_param("~lang_id", "en_GB")

    client = actionlib.SimpleActionClient("/tts", TtsAction)
    rospy.loginfo("Waiting for /tts ...")
    if not client.wait_for_server(rospy.Duration(15.0)):
        rospy.logfatal("/tts not available")
        sys.exit(1)

    goal = TtsGoal()
    goal.rawtext.text = text
    goal.rawtext.lang_id = lang
    rospy.loginfo("Sending (%s): %s", lang, text)
    client.send_goal(goal)
    if not client.wait_for_result(rospy.Duration(60.0)):
        rospy.logfatal("TTS timed out")
        sys.exit(2)
    rospy.loginfo("Result: %s", client.get_result())


if __name__ == "__main__":
    main()
