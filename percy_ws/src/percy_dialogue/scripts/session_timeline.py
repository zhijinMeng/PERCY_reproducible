"""Session timeline for PERCY benchmark (align dialogue turns to A/V recording)."""
from __future__ import print_function

import json
import os
import time

import rospy


def default_data_root():
    return os.environ.get("PERCY_DATA_DIR", "/tmp/percy_data")


def session_dir(data_root, session_id):
    return os.path.join(data_root, str(session_id))


def utterances_dir(session_out_dir, subdir="utterances"):
    """Per-session folder for user speech slices (keeps session root tidy)."""
    path = os.path.join(session_out_dir, subdir)
    os.makedirs(path, exist_ok=True)
    return path


def user_utterance_wav_path(session_out_dir, turn_idx, subdir="utterances"):
    return os.path.join(utterances_dir(session_out_dir, subdir), "user_%04d.wav" % int(turn_idx))


class SessionTimeline(object):
    """Timeline origin = recording_meta.first_image_stamp (= start of audio.wav / video t=0)."""

    def __init__(self, session_id, data_root=None):
        self.session_id = str(session_id)
        self.data_root = data_root or default_data_root()
        self.out_dir = session_dir(self.data_root, self.session_id)
        os.makedirs(self.out_dir, exist_ok=True)
        self.meta_path = os.path.join(self.out_dir, "recording_meta.json")
        self.timeline_path = os.path.join(self.out_dir, "dialogue_timeline.json")
        self.t0_ros = None
        self.t0_source = None
        self.turns = []

    def resolve_origin(self, timeout_sec=60.0, poll_sec=0.25):
        deadline = time.time() + timeout_sec
        while time.time() < deadline and not rospy.is_shutdown():
            origin = self._read_timeline_origin()
            if origin is not None:
                self.t0_ros, self.t0_source = origin
                self._write_timeline()
                rospy.loginfo(
                    "Timeline origin: %.3f (%s)", self.t0_ros, self.t0_source
                )
                return self.t0_ros
            rospy.sleep(poll_sec)
        self.t0_ros = rospy.Time.now().to_sec()
        self.t0_source = "dialogue_fallback_ros_now"
        self._write_timeline()
        rospy.logwarn(
            "No recording_meta.first_image_stamp within %.0fs; fallback t0=%.3f",
            timeout_sec,
            self.t0_ros,
        )
        return self.t0_ros

    def t_sec(self, ros_sec):
        if self.t0_ros is None or ros_sec is None:
            return None
        return round(float(ros_sec) - self.t0_ros, 4)

    def add_turn(self, row):
        self.turns.append(row)
        self._write_timeline()

    def _read_timeline_origin(self):
        if not os.path.isfile(self.meta_path):
            return None
        try:
            with open(self.meta_path, "r") as f:
                meta = json.load(f)
            wall = meta.get("recording_started_wall_ros")
            if wall is not None:
                return float(wall), "recording_meta.recording_started_wall_ros"
            stamp = meta.get("first_image_stamp")
            if stamp is None:
                return None
            return float(stamp), "recording_meta.first_image_stamp"
        except (IOError, ValueError, TypeError):
            return None

    def _write_timeline(self):
        doc = {
            "session_id": self.session_id,
            "timeline_origin_ros_sec": self.t0_ros,
            "timeline_origin_source": self.t0_source,
            "note": (
                "t_start_sec / t_end_sec are seconds from timeline origin. "
                "Prefer recording_meta.recording_started_wall_ros (laptop clock) "
                "so dialogue rospy.Time matches audio.wav t=0; "
                "first_image_stamp uses the camera header clock and may skew."
            ),
            "turns": self.turns,
        }
        with open(self.timeline_path, "w") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
