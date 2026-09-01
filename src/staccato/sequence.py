from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .exif import read_capture_times
from .timing import derive_duration_per_image

IMAGE_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}


@dataclass
class ResolvedSegment:
    file: Path
    type: str  # "image" | "video"
    duration: float | None = None  # None => derive from duration_per_image/total_duration
    transition_in: str | None = None  # None => use the global default
    trim_start: float | None = None
    trim_end: float | None = None


def infer_type(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return None


def scan_base_files(
    input_dir: Path, order: str, order_list: list[str] | None
) -> list[Path]:
    if order == "explicit":
        if not order_list:
            raise ValueError('order = "explicit" requires order_list in the config file')
        files = []
        for name in order_list:
            p = input_dir / name
            if not p.exists():
                raise ValueError(f"order_list references a missing file: {name}")
            files.append(p)
        return files

    candidates = [
        p for p in input_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS
    ]

    if order == "filename":
        return sorted(candidates, key=lambda p: p.name)

    if order == "timestamp":
        times = read_capture_times(candidates)

        def sort_key(p: Path) -> tuple:
            t = times.get(p)
            if t is not None:
                return (0, t, p.name)
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            return (1, mtime, p.name)

        return sorted(candidates, key=sort_key)

    raise ValueError(f"unknown order mode: {order!r}")


def apply_segment_overrides(
    base_files: list[Path], input_dir: Path, segment_configs: list[dict]
) -> list[ResolvedSegment]:
    segments = [ResolvedSegment(file=f, type="image") for f in base_files]
    by_name = {s.file.name: s for s in segments}

    overrides, insertions = [], []
    for raw in segment_configs:
        (overrides if raw["file"] in by_name else insertions).append(raw)

    for raw in overrides:
        seg = by_name[raw["file"]]
        _apply_fields(seg, raw)

    for raw in insertions:
        name = raw["file"]
        path = input_dir / name
        if not path.exists():
            raise ValueError(f"segment file not found: {name}")
        seg_type = raw.get("type") or infer_type(path)
        if seg_type is None:
            raise ValueError(
                f'cannot infer type for {name!r}; set type = "image" or "video" explicitly'
            )
        seg = ResolvedSegment(file=path, type=seg_type)
        _apply_fields(seg, raw)

        after, before = raw.get("after"), raw.get("before")
        if after and before:
            raise ValueError(f"segment {name!r}: 'after' and 'before' are mutually exclusive")
        if after:
            idx = _find_index(segments, after)
            segments.insert(idx + 1, seg)
        elif before:
            idx = _find_index(segments, before)
            segments.insert(idx, seg)
        else:
            raise ValueError(
                f"segment {name!r} is not part of the base sequence; "
                "'after' or 'before' is required to place it"
            )
        by_name[name] = seg

    return segments


def _find_index(segments: list[ResolvedSegment], name: str) -> int:
    for i, s in enumerate(segments):
        if s.file.name == name:
            return i
    raise ValueError(f"segment anchor not found: {name}")


def _apply_fields(seg: ResolvedSegment, raw: dict) -> None:
    if "type" in raw:
        seg.type = raw["type"]
    if "duration" in raw:
        seg.duration = float(raw["duration"])
    if "transition_in" in raw:
        seg.transition_in = raw["transition_in"]
    if "trim_start" in raw:
        seg.trim_start = float(raw["trim_start"])
    if "trim_end" in raw:
        seg.trim_end = float(raw["trim_end"])


def resolve_durations(
    segments: list[ResolvedSegment],
    duration_per_image: float | None,
    total_duration: float | None,
    transition_duration: float,
    probe_video_duration,
) -> list[float]:
    if duration_per_image is None and total_duration is None:
        raise ValueError("either duration_per_image or total_duration must be set")

    fixed_sum = 0.0
    default_indices = []
    lengths: list[float | None] = [None] * len(segments)

    for i, seg in enumerate(segments):
        if seg.type == "video":
            if seg.trim_start is not None and seg.trim_end is not None:
                lengths[i] = seg.trim_end - seg.trim_start
            else:
                lengths[i] = probe_video_duration(seg.file)
            fixed_sum += lengths[i]
        elif seg.duration is not None:
            lengths[i] = seg.duration
            fixed_sum += seg.duration
        else:
            default_indices.append(i)

    if duration_per_image is not None:
        default = duration_per_image
    else:
        n_junctions = len(segments) - 1
        default = derive_duration_per_image(
            total_duration, fixed_sum, len(default_indices), transition_duration, n_junctions
        )

    for i in default_indices:
        lengths[i] = default

    return lengths  # type: ignore[return-value]
