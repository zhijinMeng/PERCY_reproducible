#!/usr/bin/env python3
"""Move legacy utterance_*.wav in session root into utterances/user_*.wav."""
from __future__ import print_function

import argparse
import glob
import json
import os
import re
import shutil


def _rewrite_wav_fields(obj, session_dir, utterances_dir):
    if isinstance(obj, dict):
        for key, val in list(obj.items()):
            if key == "wav" and isinstance(val, str):
                base = os.path.basename(val)
                m = re.match(r"utterance_(\d+)\.wav$", base)
                if m:
                    obj[key] = os.path.join(
                        utterances_dir, "user_%s.wav" % m.group(1)
                    )
            else:
                _rewrite_wav_fields(val, session_dir, utterances_dir)
    elif isinstance(obj, list):
        for item in obj:
            _rewrite_wav_fields(item, session_dir, utterances_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir")
    parser.add_argument(
        "--utterances-subdir", default="utterances", help="target subfolder name"
    )
    args = parser.parse_args()
    session_dir = os.path.abspath(args.session_dir)
    utt_dir = os.path.join(session_dir, args.utterances_subdir)
    os.makedirs(utt_dir, exist_ok=True)

    moved = 0
    for path in sorted(glob.glob(os.path.join(session_dir, "utterance_*.wav"))):
        m = re.search(r"utterance_(\d+)\.wav$", os.path.basename(path))
        if not m:
            continue
        dest = os.path.join(utt_dir, "user_%s.wav" % m.group(1))
        if os.path.isfile(dest):
            print("skip (exists):", dest)
            continue
        shutil.move(path, dest)
        print("moved:", os.path.basename(path), "->", dest)
        moved += 1

    for name in ("chat_history.json", "dialogue_timeline.json"):
        path = os.path.join(session_dir, name)
        if not os.path.isfile(path):
            continue
        with open(path, "r") as f:
            data = json.load(f)
        _rewrite_wav_fields(data, session_dir, utt_dir)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print("updated paths in", name)

    print("done (%d wav moved)" % moved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
