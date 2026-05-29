#!/usr/bin/env python3

import wave
import rospy
from audio_common_msgs.msg import AudioData
import os

from percy_paths import percy_data_dir

AUDIO_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_WIDTH = 2


def channel_callback(msg, wf):
    wf.writeframes(msg.data)

if __name__ == '__main__':
    # call the relevant service
    rospy.init_node('record_audio')

    # Get the output file name from the parameter
    id = rospy.get_param('~id', '0')
    file_name = str(id) + '/audio.wav'
    output_file_path = os.path.join(percy_data_dir(__file__), file_name)
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

    wf = wave.open(output_file_path, 'wb') #change output directory as desired
    wf.setnchannels(AUDIO_CHANNELS)
    wf.setsampwidth(AUDIO_WIDTH)
    wf.setframerate(AUDIO_RATE) 

    #Record processed audio, corresponding to channel 0
    rospy.Subscriber('external_microphone', AudioData, channel_callback, wf)

    print("recording...")
    rospy.spin()
    print("saving...")
    wf.close()