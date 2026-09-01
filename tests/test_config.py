"""Unit tests for staccato.config: staccato.toml loading and the
CLI-flag > config-file > default merge precedence."""

from __future__ import annotations

from pathlib import Path

import pytest

from staccato.config import (
    DEFAULT_FPS,
    DEFAULT_MAX_DIMENSION,
    DEFAULT_OUTPUT,
    DEFAULT_TOTAL_DURATION,
    DEFAULT_TRANSITION,
    DEFAULT_TRANSITION_DURATION,
    load_raw_config,
    resolve_build_options,
    segment_table,
)

EMPTY_CLI = dict(
    duration_per_image=None,
    total_duration=None,
    transition_duration=None,
    transition=None,
    order=None,
    fps=None,
    output=None,
    max_dimension=None,
)


def test_defaults_when_nothing_set():
    options = resolve_build_options(EMPTY_CLI, {})
    assert options.duration_per_image is None
    assert options.total_duration == DEFAULT_TOTAL_DURATION
    assert options.transition_duration == DEFAULT_TRANSITION_DURATION
    assert options.transition == DEFAULT_TRANSITION
    assert options.order == "timestamp"
    assert options.fps == DEFAULT_FPS
    assert options.output == DEFAULT_OUTPUT
    assert options.max_dimension == DEFAULT_MAX_DIMENSION


def test_config_file_values_used_when_no_cli_override():
    raw = {"build": {"fps": 24, "transition": "wipe-left"}}
    options = resolve_build_options(EMPTY_CLI, raw)
    assert options.fps == 24
    assert options.transition == "wipe-left"


def test_cli_overrides_win_over_config_file():
    raw = {"build": {"fps": 24}}
    cli = {**EMPTY_CLI, "fps": 60}
    options = resolve_build_options(cli, raw)
    assert options.fps == 60


def test_cli_duration_pair_wins_over_config_pair_entirely():
    # Config sets total_duration; CLI sets duration_per_image. CLI's
    # choice of *which* field to use should win outright, not merge
    # field-by-field.
    raw = {"build": {"total_duration": 200}}
    cli = {**EMPTY_CLI, "duration_per_image": 2.0}
    options = resolve_build_options(cli, raw)
    assert options.duration_per_image == 2.0
    assert options.total_duration is None


def test_config_setting_both_duration_fields_is_invalid():
    raw = {"build": {"duration_per_image": 1.0, "total_duration": 100}}
    with pytest.raises(ValueError):
        resolve_build_options(EMPTY_CLI, raw)


def test_invalid_transition_raises():
    raw = {"build": {"transition": "bogus"}}
    with pytest.raises(ValueError):
        resolve_build_options(EMPTY_CLI, raw)


def test_output_is_coerced_to_path():
    raw = {"build": {"output": "out.mp4"}}
    options = resolve_build_options(EMPTY_CLI, raw)
    assert options.output == Path("out.mp4")


def test_order_list_and_random_pool_pass_through():
    raw = {
        "build": {
            "order": "explicit",
            "order_list": ["a.jpg", "b.jpg"],
            "random_pool": ["fade", "cut"],
        }
    }
    options = resolve_build_options(EMPTY_CLI, raw)
    assert options.order_list == ["a.jpg", "b.jpg"]
    assert options.random_pool == ["fade", "cut"]


def test_load_raw_config_none_path_returns_empty_dict():
    assert load_raw_config(None) == {}


def test_load_raw_config_reads_toml(tmp_path):
    config_path = tmp_path / "staccato.toml"
    config_path.write_text('[build]\nfps = 15\n')
    raw = load_raw_config(config_path)
    assert raw == {"build": {"fps": 15}}


def test_segment_table_defaults_to_empty_list():
    assert segment_table({}) == []
    assert segment_table({"segment": [{"file": "a.jpg"}]}) == [{"file": "a.jpg"}]
