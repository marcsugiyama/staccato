"""Unit tests for staccato.sequence: directory scanning/ordering, segment
overrides vs. insertions, and per-segment duration resolution. These use
fake (empty) files and a monkeypatched EXIF reader -- no real ffmpeg,
ffprobe, or exiftool involved."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from staccato.sequence import (
    ResolvedSegment,
    apply_segment_overrides,
    infer_type,
    resolve_durations,
    scan_base_files,
)


def touch(dir_: Path, name: str) -> Path:
    p = dir_ / name
    p.write_bytes(b"")
    return p


def test_infer_type():
    assert infer_type(Path("a.heic")) == "image"
    assert infer_type(Path("a.JPG")) == "image"
    assert infer_type(Path("a.mov")) == "video"
    assert infer_type(Path("a.mp4")) == "video"
    assert infer_type(Path("a.txt")) is None


def test_scan_base_files_filters_and_sorts_by_filename(tmp_path):
    touch(tmp_path, "b.jpg")
    touch(tmp_path, "a.jpg")
    touch(tmp_path, "notes.txt")  # not an image extension, excluded

    files = scan_base_files(tmp_path, "filename", None)
    assert [f.name for f in files] == ["a.jpg", "b.jpg"]


def test_scan_base_files_explicit_uses_order_list(tmp_path):
    touch(tmp_path, "a.jpg")
    touch(tmp_path, "b.jpg")
    touch(tmp_path, "c.jpg")

    files = scan_base_files(tmp_path, "explicit", ["c.jpg", "a.jpg"])
    assert [f.name for f in files] == ["c.jpg", "a.jpg"]  # b.jpg excluded


def test_scan_base_files_explicit_requires_order_list(tmp_path):
    with pytest.raises(ValueError):
        scan_base_files(tmp_path, "explicit", None)


def test_scan_base_files_explicit_missing_file_raises(tmp_path):
    with pytest.raises(ValueError):
        scan_base_files(tmp_path, "explicit", ["missing.jpg"])


def test_scan_base_files_timestamp_orders_by_exif_with_filename_tiebreak(
    tmp_path, monkeypatch
):
    a = touch(tmp_path, "a.jpg")
    b = touch(tmp_path, "b.jpg")
    c = touch(tmp_path, "c.jpg")

    fake_times = {
        a: datetime(2024, 8, 2),
        b: datetime(2024, 8, 1),
        c: datetime(2024, 8, 2),  # ties with a; broken by filename
    }
    monkeypatch.setattr(
        "staccato.sequence.read_capture_times", lambda paths: fake_times
    )

    files = scan_base_files(tmp_path, "timestamp", None)
    assert [f.name for f in files] == ["b.jpg", "a.jpg", "c.jpg"]


def test_scan_base_files_timestamp_falls_back_to_mtime(tmp_path, monkeypatch):
    a = touch(tmp_path, "a.jpg")
    b = touch(tmp_path, "b.jpg")

    # a has no EXIF timestamp; b does, and it's chronologically earlier
    # than a's mtime -- an mtime-fallback file should still sort after any
    # file with a real EXIF timestamp, per the (0, ...) / (1, ...) tuple.
    monkeypatch.setattr(
        "staccato.sequence.read_capture_times",
        lambda paths: {a: None, b: datetime(2099, 1, 1)},
    )

    files = scan_base_files(tmp_path, "timestamp", None)
    assert [f.name for f in files] == ["b.jpg", "a.jpg"]


def test_apply_segment_overrides_matches_existing_file_by_name(tmp_path):
    a = touch(tmp_path, "a.jpg")
    b = touch(tmp_path, "b.jpg")

    segments = apply_segment_overrides(
        [a, b], tmp_path, [{"file": "a.jpg", "duration": 5.0, "transition_in": "cut"}]
    )
    assert len(segments) == 2
    assert segments[0].duration == 5.0
    assert segments[0].transition_in == "cut"
    assert segments[1].duration is None


def test_apply_segment_overrides_insertion_after(tmp_path):
    a = touch(tmp_path, "a.jpg")
    b = touch(tmp_path, "b.jpg")
    touch(tmp_path, "clip.mp4")

    segments = apply_segment_overrides(
        [a, b], tmp_path, [{"file": "clip.mp4", "after": "a.jpg"}]
    )
    assert [s.file.name for s in segments] == ["a.jpg", "clip.mp4", "b.jpg"]
    assert segments[1].type == "video"  # inferred from extension


def test_apply_segment_overrides_insertion_before(tmp_path):
    a = touch(tmp_path, "a.jpg")
    b = touch(tmp_path, "b.jpg")
    touch(tmp_path, "clip.mp4")

    segments = apply_segment_overrides(
        [a, b], tmp_path, [{"file": "clip.mp4", "before": "b.jpg"}]
    )
    assert [s.file.name for s in segments] == ["a.jpg", "clip.mp4", "b.jpg"]


def test_apply_segment_overrides_insertion_requires_anchor(tmp_path):
    a = touch(tmp_path, "a.jpg")
    touch(tmp_path, "clip.mp4")

    with pytest.raises(ValueError):
        apply_segment_overrides([a], tmp_path, [{"file": "clip.mp4"}])


def test_apply_segment_overrides_insertion_after_and_before_conflict(tmp_path):
    a = touch(tmp_path, "a.jpg")
    b = touch(tmp_path, "b.jpg")
    touch(tmp_path, "clip.mp4")

    with pytest.raises(ValueError):
        apply_segment_overrides(
            [a, b],
            tmp_path,
            [{"file": "clip.mp4", "after": "a.jpg", "before": "b.jpg"}],
        )


def test_apply_segment_overrides_insertion_missing_anchor_raises(tmp_path):
    a = touch(tmp_path, "a.jpg")
    touch(tmp_path, "clip.mp4")

    with pytest.raises(ValueError):
        apply_segment_overrides(
            [a], tmp_path, [{"file": "clip.mp4", "after": "nonexistent.jpg"}]
        )


def test_apply_segment_overrides_insertion_missing_file_raises(tmp_path):
    a = touch(tmp_path, "a.jpg")

    with pytest.raises(ValueError):
        apply_segment_overrides(
            [a], tmp_path, [{"file": "missing.mp4", "after": "a.jpg"}]
        )


def test_apply_segment_overrides_insertion_unknown_extension_requires_type(tmp_path):
    a = touch(tmp_path, "a.jpg")
    touch(tmp_path, "mystery.xyz")

    with pytest.raises(ValueError):
        apply_segment_overrides(
            [a], tmp_path, [{"file": "mystery.xyz", "after": "a.jpg"}]
        )

    # ...but an explicit type sidesteps the inference failure.
    segments = apply_segment_overrides(
        [a],
        tmp_path,
        [{"file": "mystery.xyz", "after": "a.jpg", "type": "video"}],
    )
    assert segments[1].type == "video"


def test_resolve_durations_uses_duration_per_image_for_defaults():
    segments = [
        ResolvedSegment(file=Path("a.jpg"), type="image"),
        ResolvedSegment(file=Path("b.jpg"), type="image", duration=9.0),
    ]
    lengths = resolve_durations(segments, 2.0, None, 0.1, probe_video_duration=None)
    assert lengths == [2.0, 9.0]


def test_resolve_durations_derives_default_from_total_duration():
    segments = [ResolvedSegment(file=Path(f"{i}.jpg"), type="image") for i in range(4)]
    lengths = resolve_durations(segments, None, 10.0, 0.2, probe_video_duration=None)
    # 4 defaults, 3 junctions at 0.2s, target 10s -> (10 + 3*0.2)/4 = 2.65
    assert lengths == pytest.approx([2.65] * 4)


def test_resolve_durations_video_segment_uses_trim_when_given():
    segments = [
        ResolvedSegment(
            file=Path("clip.mp4"), type="video", trim_start=1.0, trim_end=3.5
        )
    ]
    lengths = resolve_durations(segments, 1.0, None, 0.1, probe_video_duration=None)
    assert lengths == [2.5]


def test_resolve_durations_video_segment_probes_when_no_trim():
    segments = [ResolvedSegment(file=Path("clip.mp4"), type="video")]
    lengths = resolve_durations(
        segments, 1.0, None, 0.1, probe_video_duration=lambda p: 7.0
    )
    assert lengths == [7.0]


def test_resolve_durations_requires_a_duration_source():
    segments = [ResolvedSegment(file=Path("a.jpg"), type="image")]
    with pytest.raises(ValueError):
        resolve_durations(segments, None, None, 0.1, probe_video_duration=None)
