#!/usr/bin/env python3
"""Detect laptop USB mic (RØDE NT-USB+ etc.) → plughw:CARD,0 for arecord."""
from __future__ import print_function

import argparse
import os
import re
import subprocess
import sys

# Substrings in card name (uppercased); first match wins among preferred.
PREFERRED = (
    "NTUSB",
    "NT-USB",
    "RODE",
    "RØDE",
    "VIDEOMIC",
    "PODCAST",
)

SKIP = (
    "HDA INTEL",
    "HDA ATI",
    "SOF HDA",
    "PCH",
    "HDMI",
    "MONITOR",
    "DUMMY",
    "LOOPBACK",
    "BUILTIN",
    "BUILTIN-MIC",
    "WEBCAM",  # often weak; prefer explicit USB audio iface
)


def _parse_arecord_l(text):
    cards = []
    for line in text.splitlines():
        m = re.match(r"^card (\d+):\s*(\S+)\s+\[(.*)\]", line.strip())
        if m:
            cards.append({"id": m.group(1), "short": m.group(2), "name": m.group(3)})
    return cards


def _parse_proc_asound(text):
    cards = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+\[([^\]]+)\]:\s*(.+)", line)
        if m:
            cards.append({"id": m.group(1), "short": m.group(2).strip(), "name": m.group(3).strip()})
    return cards


def _list_cards():
    cards = []
    try:
        out = subprocess.check_output(
            ["arecord", "-l"], stderr=subprocess.STDOUT, universal_newlines=True
        )
        cards = _parse_arecord_l(out)
    except (OSError, subprocess.CalledProcessError):
        pass
    if cards:
        return cards
    proc = "/proc/asound/cards"
    if os.path.isfile(proc):
        with open(proc, "r") as f:
            return _parse_proc_asound(f.read())
    return []


def _label(card):
    return "{} {} {}".format(
        card.get("id", ""),
        card.get("short", ""),
        card.get("name", ""),
    ).upper()


def _score(card):
    name = _label(card)
    for skip in SKIP:
        if skip in name:
            return -1
    for pref in PREFERRED:
        if pref.upper() in name:
            return 100
    if "USB" in name and ("AUDIO" in name or "MIC" in name):
        return 50
    return 0


def detect_host_usb_mic(device_sub=0):
    """Return plughw:CARD,sub for best USB mic, or '' if none."""
    best = None
    best_score = 0
    for card in _list_cards():
        sc = _score(card)
        if sc > best_score:
            best_score = sc
            best = card
    if not best or best_score <= 0:
        return ""
    return "plughw:{},{}".format(best["id"], int(device_sub))


def host_usb_mic_present():
    return bool(detect_host_usb_mic())


def main():
    p = argparse.ArgumentParser(description="Detect host USB microphone (ALSA plughw).")
    p.add_argument(
        "--print-device",
        action="store_true",
        help="Print plughw:CARD,0 (empty if not found); exit 0 either way",
    )
    p.add_argument(
        "--present",
        action="store_true",
        help="Exit 0 if a host USB mic is detected, else exit 1",
    )
    p.add_argument("--device-sub", type=int, default=0)
    args = p.parse_args()
    dev = detect_host_usb_mic(device_sub=args.device_sub)
    if args.present:
        return 0 if dev else 1
    if args.print_device:
        print(dev, end="")
        return 0
    if dev:
        print(dev)
        return 0
    print("No host USB mic found (plug in Rode / check arecord -l)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
