"""End-to-end tests that actually invoke ffmpeg/ffprobe/exiftool against
real files. Slower than the unit tests, so kept to a small number covering
the default path and the full config-driven feature set (explicit order,
segment overrides, a "cut" transition, and an inserted+trimmed video
clip) -- mirrors the manual verification done while building this tool.

Skipped automatically if ffmpeg/ffprobe/exiftool aren't on PATH.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from click.testing import CliRunner

from staccato import deps
from staccato.cli import cli

_missing = deps.missing_tools()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _missing != [], reason=f"missing required tool(s): {', '.join(_missing)}"
    ),
]


def probe(path, *entries):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", ":".join(entries),
         "-of", "default=noprint_wrappers=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.strip().splitlines())


def test_build_default_settings_against_samples(samples_dir, tmp_path):
    out = tmp_path / "out.mp4"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "build", str(samples_dir), "-o", str(out),
        "--duration-per-image", "0.3", "--transition-duration", "0.05",
        "--max-dimension", "320",
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()

    info = probe(out, "format=duration", "stream=width,height,codec_name")
    # 6 sample images, 0.3s each, 5 transitions at 0.05s:
    # 6*0.3 - 5*0.05 = 1.55s (allowing for frame-rate quantization).
    assert float(info["duration"]) == pytest.approx(1.55, abs=0.15)
    assert info["codec_name"] == "h264"
    assert int(info["width"]) == 320
    assert int(info["height"]) == 320


def test_build_with_explicit_order_overrides_and_video_insertion(
    samples_dir, tmp_path
):
    work = tmp_path / "project"
    work.mkdir()
    sample_files = sorted(samples_dir.glob("*.jpg"))[:3]
    for f in sample_files:
        shutil.copy(f, work / f.name)
    names = [f.name for f in sample_files]

    clip = work / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=4:size=320x240:rate=30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
    )

    (work / "staccato.toml").write_text(f"""
[build]
order = "explicit"
order_list = {names!r}
duration_per_image = 1.0
transition_duration = 0.2
fps = 30

[[segment]]
file = "{names[1]}"
transition_in = "cut"

[[segment]]
file = "clip.mp4"
type = "video"
after = "{names[0]}"
trim_start = 0.5
trim_end = 1.5
""")

    out = tmp_path / "out.mp4"
    runner = CliRunner()
    result = runner.invoke(cli, ["build", str(work), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()

    info = probe(out, "format=duration")
    # clip.mp4 is inserted after name0, so the final order is:
    # name0 (1.0s), clip (1.0s trimmed), name1 (1.0s), name2 (1.0s).
    # name1's transition_in="cut" now applies to the clip->name1 junction
    # (the one immediately preceding name1, wherever it ends up), not
    # name0->name1 -- the insertion shifts which junction it lands on.
    # Junctions: name0->clip=0.2, clip->name1=1/30 (cut), name1->name2=0.2.
    expected = (1.0 + 1.0 + 1.0 + 1.0) - (0.2 + 1 / 30 + 0.2)
    assert float(info["duration"]) == pytest.approx(expected, abs=0.15)
