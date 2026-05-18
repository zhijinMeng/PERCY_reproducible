#!/usr/bin/env python3
import rospy
import wave
import os
from sensor_msgs.msg import Image
from chatting_system.msg import AudioStamped
from cv_bridge import CvBridge
import cv2

from percy_paths import percy_data_dir

# Constants for audio
AUDIO_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_WIDTH = 2

# Global variables for the WAV file handler and video writer
wf = None
video_writer = None
bridge = CvBridge()

# Initialize the WAV file for audio recording
def initialize_wav_file(filename, sample_width=2, channels=1, sample_rate=16000):
    directory = os.path.dirname(filename)
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    global wf
    wf = wave.open(filename, 'wb')
    wf.setnchannels(channels)
    wf.setsampwidth(sample_width)
    wf.setframerate(sample_rate)

    rospy.loginfo("Initialized .wav file: %s", filename)

# Initialize the video writer for video recording
def initialize_video_writer(filename, width=640, height=480, fps=30):
    global video_writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(filename, fourcc, fps, (width, height))
    rospy.loginfo("Initialized video file: %s", filename)

# Save audio data to the WAV file
def save_audio_to_wav(data):
    global wf
    if wf is not None:
        wf.writeframes(data)
        rospy.loginfo("Recording audio -> reminder")
    else:
        rospy.logwarn("Wave file handler is not initialized.")

# Save video frame to the video file
def save_video_frame(image_msg):
    global video_writer
    if video_writer is not None:
        try:
            cv_image = bridge.imgmsg_to_cv2(image_msg, "bgr8")
            video_writer.write(cv_image)
        except Exception as e:
            rospy.logerr("Error converting or saving video frame: %s", str(e))
    else:
        rospy.logwarn("Video writer is not initialized.")

# Audio callback function
def audio_callback(audio_msg):
    try:
        rospy.loginfo("Audio Timestamp: %s.%s", audio_msg.header.stamp.secs, audio_msg.header.stamp.nsecs)
        save_audio_to_wav(audio_msg.data)
    except Exception as e:
        rospy.logerr("Error in audio callback: %s", str(e))

# Video callback function
def video_callback(image_msg):
    try:
        rospy.loginfo("Image Timestamp: %s.%s", image_msg.header.stamp.secs, image_msg.header.stamp.nsecs)
        save_video_frame(image_msg)
    except Exception as e:
        rospy.logerr("Error in video callback: %s", str(e))

# Handle shutdown process
def shutdown_hook():
    global wf, video_writer
    if wf is not None:
        wf.close()
        rospy.loginfo("Closed .wav file.")
    if video_writer is not None:
        video_writer.release()
        rospy.loginfo("Closed video file.")

# Main listener function
def listener():
    global wf, video_writer

    rospy.init_node('audio_video_recorder', anonymous=True)

    # Get the parameter ID and create save paths
    id = rospy.get_param('~id', '0')
    base = percy_data_dir(__file__)
    AUDIO_SAVE_PATH = os.path.join(base, str(id), "audio.wav")
    VIDEO_SAVE_PATH = os.path.join(base, str(id), "whole_video.mp4")

    # Initialize the WAV file and video writer
    initialize_wav_file(AUDIO_SAVE_PATH, AUDIO_WIDTH, AUDIO_CHANNELS, AUDIO_RATE)
    initialize_video_writer(VIDEO_SAVE_PATH, 640, 480, 30)

    # Subscribe to the audio and video topics
    rospy.Subscriber('external_microphone', AudioStamped, audio_callback)
    rospy.Subscriber('fixed_video', Image, video_callback)
    
    rospy.loginfo("Recording node started, waiting for messages...")

    rospy.on_shutdown(shutdown_hook)
    
    try:
        rospy.spin()
    except rospy.ROSInterruptException:
        rospy.loginfo("Shutting down recording node...")

if __name__ == '__main__':
    listener()
