#!/usr/bin/env python3
"""Subscribe /audio/rode (or any AudioData topic) and write mono WAV on shutdown."""
from __future__ import print_function

import os
import struct
import wave

import rospy
from audio_common_msgs.msg import AudioData


class HostMicWavRecorder(object):
    def __init__(self):
        rospy.init_node("host_mic_wav_recorder")
        self._topic = str(rospy.get_param("~audio_topic", "/audio/rode"))
        self._rate = int(rospy.get_param("~sample_rate", 16000))
        self._session = str(rospy.get_param("~session_id", "mic_ros"))
        root = str(rospy.get_param("~output_root", "__auto__"))
        if root in ("", "__auto__"):
            root = os.environ.get("PERCY_DATA_DIR", "/workspace/percy_data")
        self._out_dir = os.path.join(root, self._session)
        os.makedirs(self._out_dir, exist_ok=True)
        self._wav_path = os.path.join(self._out_dir, "audio.wav")
        self._buf = bytearray()
        self._sub = rospy.Subscriber(
            self._topic, AudioData, self._cb, queue_size=200, buff_size=2**20
        )
        rospy.loginfo(
            "host_mic_wav_recorder: topic=%s -> %s (Ctrl+C to stop)",
            self._topic,
            self._wav_path,
        )

    def _cb(self, msg):
        self._buf.extend(msg.data)

    def finalize(self):
        with wave.open(self._wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._rate)
            wf.writeframes(bytes(self._buf))
        n = len(self._buf) // 2
        rospy.loginfo("Wrote %s (%.2fs)", self._wav_path, n / float(self._rate))


def main():
    rec = HostMicWavRecorder()
    try:
        rospy.spin()
    finally:
        rec.finalize()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
