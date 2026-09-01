from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import transitions
from .sequence import ResolvedSegment
from .timing import compute_offsets


def normalize_image(src: Path, dst: Path) -> None:
    """Decode any still (HEIC/JPEG/PNG/...) to a PNG, applying EXIF
    orientation and assembling any tiled HEIC grid, via ffmpeg's decoder."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), str(dst)],
        check=True,
    )


def probe_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def build_video(
    segments: list[ResolvedSegment],
    lengths: list[float],
    transition_duration: float,
    default_transition: str,
    random_pool: list[str] | None,
    fps: int,
    output: Path,
    max_dimension: int = 0,
) -> None:
    if len(segments) != len(lengths):
        raise ValueError("segments and lengths must be the same length")
    if not segments:
        raise ValueError("no segments to render")

    with tempfile.TemporaryDirectory(prefix="staccato-") as tmp:
        tmp_dir = Path(tmp)
        frame_paths = _normalize_all(segments, tmp_dir)
        target_w, target_h = _target_dimensions(segments, frame_paths, max_dimension)

        junction_types, junction_durations = _resolve_junctions(
            segments, transition_duration, default_transition, random_pool, fps
        )
        offsets, _total = compute_offsets(lengths, junction_durations)

        cmd = _build_ffmpeg_command(
            segments, frame_paths, lengths, offsets, junction_types,
            junction_durations, target_w, target_h, fps, output,
        )
        subprocess.run(cmd, check=True)


def _normalize_all(segments: list[ResolvedSegment], tmp_dir: Path) -> list[Path]:
    frame_paths: list[Path] = []
    for i, seg in enumerate(segments):
        if seg.type == "image":
            png = tmp_dir / f"frame_{i:04d}.png"
            normalize_image(seg.file, png)
            frame_paths.append(png)
        else:
            frame_paths.append(seg.file)
    return frame_paths


def _target_dimensions(
    segments: list[ResolvedSegment], frame_paths: list[Path], max_dimension: int
) -> tuple[int, int]:
    w, h = probe_dimensions(frame_paths[0])
    if max_dimension and max(w, h) > max_dimension:
        scale = max_dimension / max(w, h)
        w, h = round(w * scale), round(h * scale)
    # yuv420p requires even dimensions.
    return w - (w % 2), h - (h % 2)


def _resolve_junctions(
    segments: list[ResolvedSegment],
    transition_duration: float,
    default_transition: str,
    random_pool: list[str] | None,
    fps: int,
) -> tuple[list[str], list[float]]:
    types, durations = [], []
    for seg in segments[1:]:
        raw = seg.transition_in or default_transition
        xfade_name, duration = transitions.resolve(raw, transition_duration, fps, random_pool)
        types.append(xfade_name)
        durations.append(duration)
    return types, durations


def _build_ffmpeg_command(
    segments: list[ResolvedSegment],
    frame_paths: list[Path],
    lengths: list[float],
    offsets: list[float],
    junction_types: list[str],
    junction_durations: list[float],
    width: int,
    height: int,
    fps: int,
    output: Path,
) -> list[str]:
    cmd = ["ffmpeg", "-y", "-v", "error"]

    for seg, path, length in zip(segments, frame_paths, lengths):
        if seg.type == "image":
            cmd += ["-loop", "1", "-t", f"{length}", "-i", str(path)]
        else:
            if seg.trim_start is not None:
                cmd += ["-ss", f"{seg.trim_start}"]
            cmd += ["-t", f"{length}", "-i", str(path)]

    filters = []
    for i in range(len(segments)):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]"
        )

    label = "v0"
    for i in range(1, len(segments)):
        out_label = f"vx{i}" if i < len(segments) - 1 else "vout"
        filters.append(
            f"[{label}][v{i}]xfade=transition={junction_types[i - 1]}:"
            f"duration={junction_durations[i - 1]}:offset={offsets[i - 1]}[{out_label}]"
        )
        label = out_label

    if len(segments) == 1:
        final_label = "v0"
    else:
        final_label = label

    filter_complex = ";\n".join(filters)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{final_label}]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output),
    ]
    return cmd
