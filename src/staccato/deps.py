"""Checks that the external tools staccato shells out to (ffmpeg, ffprobe,
exiftool) are actually on PATH before doing any real work."""

from __future__ import annotations

import shutil

REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "exiftool")


def missing_tools() -> list[str]:
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
