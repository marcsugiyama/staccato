"""CLI-level tests: argument parsing, validation, and CLI/config
precedence, via click's CliRunner. The dependency preflight check and the
actual ffmpeg pipeline (staccato.cli.build_video) are stubbed out so these
run fast and don't require ffmpeg/exiftool to be installed."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from staccato.cli import cli


@pytest.fixture(autouse=True)
def no_missing_tools(monkeypatch):
    monkeypatch.setattr("staccato.deps.missing_tools", lambda: [])


@pytest.fixture
def recorded_build(monkeypatch):
    calls = []

    def fake_build_video(segments, lengths, transition_duration, transition,
                          random_pool, fps, output, max_dimension=0, use_cache=True):
        calls.append(dict(
            segments=segments, lengths=lengths,
            transition_duration=transition_duration, transition=transition,
            random_pool=random_pool, fps=fps, output=output,
            max_dimension=max_dimension, use_cache=use_cache,
        ))

    monkeypatch.setattr("staccato.cli.build_video", fake_build_video)
    return calls


def make_images(dir_: Path, names: list[str]) -> None:
    for name in names:
        (dir_ / name).write_bytes(b"")


def test_build_runs_with_defaults(tmp_path, recorded_build):
    make_images(tmp_path, ["a.jpg", "b.jpg", "c.jpg"])
    runner = CliRunner()
    result = runner.invoke(cli, [
        "build", str(tmp_path), "--order", "filename",
        "--duration-per-image", "1", "-o", str(tmp_path / "out.mp4"),
    ])
    assert result.exit_code == 0, result.output
    assert len(recorded_build) == 1
    call = recorded_build[0]
    assert [s.file.name for s in call["segments"]] == ["a.jpg", "b.jpg", "c.jpg"]
    assert call["transition"] == "fade"
    assert call["transition_duration"] == 0.1
    assert call["fps"] == 30
    assert call["max_dimension"] == 1920
    assert call["output"] == tmp_path / "out.mp4"
    assert call["use_cache"] is True


def test_no_cache_flag_disables_caching(tmp_path, recorded_build):
    make_images(tmp_path, ["a.jpg"])
    runner = CliRunner()
    result = runner.invoke(cli, [
        "build", str(tmp_path), "--order", "filename",
        "--duration-per-image", "1", "--no-cache",
    ])
    assert result.exit_code == 0, result.output
    assert recorded_build[0]["use_cache"] is False


def test_duration_flags_are_mutually_exclusive(tmp_path):
    make_images(tmp_path, ["a.jpg"])
    runner = CliRunner()
    result = runner.invoke(cli, [
        "build", str(tmp_path),
        "--duration-per-image", "1", "--total-duration", "10",
    ])
    assert result.exit_code == 2
    assert "mutually exclusive" in result.output


def test_invalid_transition_rejected(tmp_path):
    make_images(tmp_path, ["a.jpg"])
    runner = CliRunner()
    result = runner.invoke(cli, [
        "build", str(tmp_path), "--transition", "bogus",
    ])
    assert result.exit_code == 2
    assert "not a known transition" in result.output


def test_input_dir_must_exist():
    runner = CliRunner()
    result = runner.invoke(cli, ["build", "/no/such/directory"])
    assert result.exit_code == 2


def test_missing_dependencies_reported(monkeypatch, tmp_path):
    make_images(tmp_path, ["a.jpg"])
    monkeypatch.setattr(
        "staccato.deps.missing_tools", lambda: ["ffmpeg", "exiftool"]
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["build", str(tmp_path)])
    assert result.exit_code != 0
    assert "ffmpeg" in result.output and "exiftool" in result.output


def test_config_file_is_auto_discovered(tmp_path, recorded_build):
    make_images(tmp_path, ["a.jpg", "b.jpg"])
    (tmp_path / "staccato.toml").write_text(
        '[build]\nfps = 15\norder = "filename"\nduration_per_image = 1.0\n'
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["build", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert recorded_build[0]["fps"] == 15


def test_cli_flag_overrides_auto_discovered_config(tmp_path, recorded_build):
    make_images(tmp_path, ["a.jpg", "b.jpg"])
    (tmp_path / "staccato.toml").write_text(
        '[build]\nfps = 15\norder = "filename"\nduration_per_image = 1.0\n'
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["build", str(tmp_path), "--fps", "60"])
    assert result.exit_code == 0, result.output
    assert recorded_build[0]["fps"] == 60


def test_explicit_order_without_order_list_is_a_clear_error(tmp_path):
    make_images(tmp_path, ["a.jpg"])
    (tmp_path / "staccato.toml").write_text('[build]\norder = "explicit"\n')
    runner = CliRunner()
    result = runner.invoke(cli, ["build", str(tmp_path)])
    assert result.exit_code != 0
    assert "order_list" in result.output


def test_align_reports_not_implemented(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["align", str(tmp_path)])
    assert result.exit_code != 0
    assert "not yet implemented" in result.output


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flag_works_at_group_and_subcommand_level(flag):
    runner = CliRunner()
    assert runner.invoke(cli, [flag]).exit_code == 0
    assert runner.invoke(cli, ["build", flag]).exit_code == 0
    assert runner.invoke(cli, ["align", flag]).exit_code == 0
