"""Reads EXIF capture timestamps (via a single batched exiftool call) so
images can be ordered chronologically rather than by filename."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path


def read_capture_times(paths: list[Path]) -> dict[Path, datetime | None]:
    """Batch-read EXIF DateTimeOriginal for the given paths via a single
    exiftool invocation. Missing/unparseable values map to None."""
    if not paths:
        return {}
    resolved = [p.resolve() for p in paths]
    result = subprocess.run(
        ["exiftool", "-j", "-DateTimeOriginal", *[str(p) for p in resolved]],
        capture_output=True,
        text=True,
        check=True,
    )
    entries = json.loads(result.stdout)
    by_source = {Path(e["SourceFile"]).resolve(): e for e in entries}

    times: dict[Path, datetime | None] = {}
    for orig, res in zip(paths, resolved):
        raw = by_source.get(res, {}).get("DateTimeOriginal")
        times[orig] = _parse_exif_datetime(raw) if raw else None
    return times


def _parse_exif_datetime(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
