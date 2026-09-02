"""Unit test for staccato.ffmpeg_pipeline._build_ffmpeg_command: pure
string/list construction, no real ffmpeg involved."""

from __future__ import annotations

from pathlib import Path

from staccato.ffmpeg_pipeline import _build_ffmpeg_command
from staccato.sequence import ResolvedSegment


def test_crf_and_preset_land_in_the_command():
    segments = [
        ResolvedSegment(file=Path("a.png"), type="image"),
        ResolvedSegment(file=Path("b.png"), type="image"),
    ]
    cmd = _build_ffmpeg_command(
        segments=segments,
        frame_paths=[Path("a.png"), Path("b.png")],
        lengths=[1.0, 1.0],
        offsets=[0.5],
        junction_types=["fade"],
        junction_durations=[0.5],
        width=100,
        height=100,
        fps=30,
        output=Path("out.mp4"),
        crf=30,
        preset="slow",
    )
    assert "-crf" in cmd
    assert cmd[cmd.index("-crf") + 1] == "30"
    assert "-preset" in cmd
    assert cmd[cmd.index("-preset") + 1] == "slow"
