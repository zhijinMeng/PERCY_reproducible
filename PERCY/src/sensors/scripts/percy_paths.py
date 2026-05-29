"""Portable workspace paths for PERCY.

- Set PERCY_DATA_DIR to override the root directory for session data (default: <ws>/src/DATA).
- Set PERCY_CHATTING_DATA_DIR for external_tester-style recordings (default: <ws>/src/chatting_system/DATA).
"""
import os


def workspace_src_dir(script_file):
    """Resolve .../src from a script under .../src/<pkg>/scripts/."""
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(script_file)), "..", "..")
    )


def percy_data_dir(script_file):
    override = os.environ.get("PERCY_DATA_DIR")
    if override:
        return override
    return os.path.join(workspace_src_dir(script_file), "DATA")


def percy_chatting_data_dir(script_file):
    override = os.environ.get("PERCY_CHATTING_DATA_DIR")
    if override:
        return override
    return os.path.join(workspace_src_dir(script_file), "chatting_system", "DATA")
