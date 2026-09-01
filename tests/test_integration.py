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
from pathlib import Path

import pytest
from click.testing import CliRunner

from staccato import deps
from staccato.cli import cli
from staccato.ffmpeg_pipeline import normalize_image, probe_dimensions

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_missing = deps.missing_tools()
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        _missing != [], reason=f"missing required tool(s): {', '.join(_missing)}"
    ),
]


def _ffmpeg_supports_tiled_heif() -> bool:
    """Tiled/grid HEIF demuxing (what real iPhone photos use) landed in
    ffmpeg's mov demuxer via patches from February 2024, so it's only in
    ffmpeg 7.x+. Probing capability directly, rather than hardcoding a
    version check, means this self-heals if the environment's ffmpeg is
    ever upgraded -- see README.md#requirements."""
    if _missing:
        return False
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(FIXTURES_DIR / "tiled.heic"),
         "-frames:v", "1", "-f", "null", "-"],
        capture_output=True,
    )
    return result.returncode == 0


_tiled_heif_supported = _ffmpeg_supports_tiled_heif()
skip_unless_tiled_heif = pytest.mark.skipif(
    not _tiled_heif_supported,
    reason="this ffmpeg build can't decode tiled/grid HEIF; needs ffmpeg >= 7.x "
    "(see README.md#requirements)",
)


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


@skip_unless_tiled_heif
def test_normalize_image_scales_a_tiled_heic(fixtures_dir, tmp_path):
    # Regression test: a HEIC encoded as a tile/grid (as real iPhone
    # photos are) makes ffmpeg reconstruct it via its own internal
    # complex filtergraph. Combining that with our own scaling -vf in
    # one command used to fail with "Simple and complex filtering cannot
    # be used together for the same stream" -- caught only once tested
    # against a genuinely tiled HEIC, not the plain JPEG samples.
    out = tmp_path / "out.png"
    normalize_image(fixtures_dir / "tiled.heic", out, 400, 300)
    assert out.exists()
    assert probe_dimensions(out) == (400, 300)


@skip_unless_tiled_heif
def test_build_handles_tiled_heic_end_to_end(fixtures_dir, tmp_path):
    work = tmp_path / "project"
    work.mkdir()
    shutil.copy(fixtures_dir / "tiled.heic", work / "a.heic")
    shutil.copy(fixtures_dir / "tiled.heic", work / "b.heic")

    out = tmp_path / "out.mp4"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "build", str(work), "-o", str(out), "--order", "filename",
        "--duration-per-image", "0.5", "--transition-duration", "0.1",
        "--max-dimension", "300",
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()

    info = probe(out, "stream=width,height")
    # Source is 1600x1200; capped to 300 on the longer edge, aspect
    # preserved, rounded to even for yuv420p.
    assert (int(info["width"]), int(info["height"])) == (300, 224)
