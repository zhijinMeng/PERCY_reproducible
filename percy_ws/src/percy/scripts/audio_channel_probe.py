#!/usr/bin/env python3
"""Probe ARI audio topics: measure RMS / clipping over a short window."""
from __future__ import print_function

import os
import sys
import wave

import numpy as np
import rospy
from audio_common_msgs.msg import AudioData

CANDIDATE_TOPICS = [
    "/audio/channel0",
    "/audio/channel1",
    "/audio/channel2",
    "/audio/channel3",
    "/audio/channel4",
    "/audio/channel5",
    "/audio/raw",
    "/audio/speech",
]

SAMPLE_RATE = 16000


def _analyze_pcm(pcm):
    if len(pcm) < 4:
        return None
    pcm = bytes(pcm[: len(pcm) // 2 * 2])
    samples = np.frombuffer(pcm, dtype=np.int16)
    if samples.size == 0:
        return None
    abs_s = np.abs(samples.astype(np.float64))
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return {
        "samples": int(samples.size),
        "duration_sec": samples.size / float(SAMPLE_RATE),
        "rms": rms,
        "peak": int(abs_s.max()),
        "clip_frac": float(np.mean(abs_s >= 32000)),
        "silent_frac": float(np.mean(abs_s < 100)),
    }


def main():
    rospy.init_node("audio_channel_probe", anonymous=True)
    duration = float(rospy.get_param("~duration", 5.0))
    save_dir = rospy.get_param("~save_dir", "")
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)

    published = {name for name, _ in rospy.get_published_topics()}
    topics = [t for t in CANDIDATE_TOPICS if t in published]
    if not topics:
        rospy.logerr("No candidate audio topics published. Is the robot audio stack running?")
        sys.exit(1)

    buffers = {t: bytearray() for t in topics}
    counts = {t: 0 for t in topics}

    def _mk_cb(topic):
        def _cb(msg):
            buffers[topic].extend(msg.data)
            counts[topic] += 1

        return _cb

    subs = []
    for t in topics:
        subs.append(rospy.Subscriber(t, AudioData, _mk_cb(t), queue_size=200, buff_size=2**20))

    rospy.loginfo("Sampling %d topic(s) for %.1fs ...", len(topics), duration)
    rospy.sleep(duration)
    for s in subs:
        s.unregister()

    rows = []
    print("\n=== Audio topic probe (%.1fs) ===" % duration)
    print("%-40s %8s %10s %8s %8s %8s" % ("topic", "msgs", "dur(s)", "RMS", "peak", "clip%"))
    print("-" * 90)

    for t in topics:
        stats = _analyze_pcm(buffers[t])
        if stats is None:
            print("%-40s %8d   (no data)" % (t, counts[t]))
            continue
        rows.append((t, stats, counts[t]))
        print(
            "%-40s %8d %10.2f %8.0f %8d %7.2f"
            % (
                t,
                counts[t],
                stats["duration_sec"],
                stats["rms"],
                stats["peak"],
                100.0 * stats["clip_frac"],
            )
        )
        if save_dir and stats["samples"] > 0:
            safe = t.strip("/").replace("/", "_")
            wav_path = os.path.join(save_dir, "%s.wav" % safe)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(bytes(buffers[t][: stats["samples"] * 2]))

    if not rows:
        rospy.logerr("No audio bytes received on any topic.")
        sys.exit(2)

    rows.sort(key=lambda x: x[1]["rms"])
    quiet = rows[0]
    loud = rows[-1]
    print("\nQuietest (lowest RMS): %s  RMS=%.0f" % (quiet[0], quiet[1]["rms"]))
    print("Loudest:               %s  RMS=%.0f" % (loud[0], loud[1]["rms"]))
    print("\nTip: lower RMS + clip%% near 0 is usually cleaner for recording.")
    if save_dir:
        print("WAV snippets saved under: %s" % save_dir)


if __name__ == "__main__":
    main()
