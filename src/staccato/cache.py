"""Two content-addressed caches under one root (~/.cache/staccato, override
with $STACCATO_CACHE_DIR or $XDG_CACHE_HOME):

- frames/: normalized image PNGs, keyed by source file identity (path,
  size, mtime) and target dimensions -- not file content, to avoid
  hashing potentially hundreds of megabytes of HEIC data on every run
  just to check the cache. Used by `build` (ffmpeg_pipeline.py).
- transforms/: small ECC warp matrices computed by `align`, keyed by a
  whole chain prefix (see align.py) since chained alignment makes each
  image's result depend on everything before it in its chain. Separated
  from frames/ because what's cached is a handful of floats, not an
  image -- storing it as a tiny .npy is simpler than routing it through
  the PNG-shaped frame cache.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np


def _root_dir() -> Path:
    base = os.environ.get("STACCATO_CACHE_DIR")
    if not base:
        base = str(Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "staccato")
    return Path(base)


def cache_dir() -> Path:
    d = _root_dir() / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transforms_dir() -> Path:
    d = _root_dir() / "transforms"
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


def transform_key(chain_key: str) -> Path:
    key = hashlib.sha256(chain_key.encode()).hexdigest()
    return transforms_dir() / f"{key}.npy"


def get_or_compute_transform(
    chain_key: str, compute: Callable[[], np.ndarray]
) -> np.ndarray:
    """Return the cached 2x3 warp matrix for this chain prefix, computing
    it via `compute()` (the expensive ECC step) on a miss. `chain_key`
    should already encode the full prefix (see align.py's
    _chain_key) -- this function doesn't know or care what it means,
    just that identical keys mean identical results.

    numpy is imported locally, not at module level: cache.py is imported
    by ffmpeg_pipeline.py, which every `build` user needs, but numpy is
    only part of the optional `align` extra -- a plain `build` install
    shouldn't require it.
    """
    import numpy as np

    dst = transform_key(chain_key)
    if dst.exists():
        return np.load(dst)
    matrix = compute()
    tmp = dst.parent / f".tmp-{uuid.uuid4().hex}.npy"
    np.save(tmp, matrix)
    os.replace(tmp, dst)
    return matrix
