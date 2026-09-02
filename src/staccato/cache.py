"""Content-addressed cache for normalized image frames, keyed by source
file identity (path, size, mtime) and target dimensions -- not file
content, to avoid hashing potentially hundreds of megabytes of HEIC data
on every run just to check the cache. This means re-running `build` with
only transition/timing changes (same images, same --max-dimension) skips
decoding entirely."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Callable


def cache_dir() -> Path:
    base = os.environ.get("STACCATO_CACHE_DIR")
    if not base:
        base = str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "staccato")
    d = Path(base) / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(src: Path, width: int | None, height: int | None) -> Path:
    st = src.stat()
    raw = f"{src.resolve()}|{st.st_mtime_ns}|{st.st_size}|{width}x{height}"
    key = hashlib.sha256(raw.encode()).hexdigest()
    return cache_dir() / f"{key}.png"


def get_or_create(
    src: Path,
    width: int | None,
    height: int | None,
    compute: Callable[[Path, Path, int | None, int | None], None],
) -> Path:
    """Return the cached PNG for (src, width, height), computing it via
    `compute(src, dst, width, height)` on a miss. Writes to a uniquely
    named temp file and atomically renames into place, so concurrent
    callers racing on the same key can't corrupt each other's output --
    worst case, one's redundant work is discarded."""
    dst = path_for(src, width, height)
    if dst.exists():
        return dst
    tmp = dst.parent / f".tmp-{uuid.uuid4().hex}.png"
    compute(src, tmp, width, height)
    os.replace(tmp, dst)
    return dst
