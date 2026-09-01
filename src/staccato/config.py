from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .transitions import is_valid

DEFAULT_TRANSITION_DURATION = 0.1
DEFAULT_TRANSITION = "fade"
DEFAULT_ORDER = "timestamp"
DEFAULT_FPS = 30
DEFAULT_OUTPUT = Path("timelapse.mp4")
DEFAULT_TOTAL_DURATION = 120.0
DEFAULT_MAX_DIMENSION = 1920


@dataclass
class BuildOptions:
    duration_per_image: float | None
    total_duration: float | None
    transition_duration: float
    transition: str
    order: str
    order_list: list[str] | None
    random_pool: list[str] | None
    fps: int
    output: Path
    max_dimension: int  # 0 means uncapped


def load_raw_config(path: Path | None) -> dict:
    if path is None:
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def resolve_build_options(cli_overrides: dict, raw_config: dict) -> BuildOptions:
    """Merge precedence: CLI flags > config file [build] table > defaults.

    cli_overrides values that were never passed on the command line must be
    None so 'not provided' is distinguishable from 'explicitly set'.
    """
    build_table = raw_config.get("build", {})

    def pick(key, default):
        if cli_overrides.get(key) is not None:
            return cli_overrides[key]
        if key in build_table:
            return build_table[key]
        return default

    duration_per_image, total_duration = _resolve_duration_pair(cli_overrides, build_table)

    transition = pick("transition", DEFAULT_TRANSITION)
    if not is_valid(transition):
        raise ValueError(f"invalid transition: {transition!r}")

    output = pick("output", DEFAULT_OUTPUT)
    if not isinstance(output, Path):
        output = Path(output)

    return BuildOptions(
        duration_per_image=duration_per_image,
        total_duration=total_duration,
        transition_duration=pick("transition_duration", DEFAULT_TRANSITION_DURATION),
        transition=transition,
        order=pick("order", DEFAULT_ORDER),
        order_list=build_table.get("order_list"),
        random_pool=build_table.get("random_pool"),
        fps=pick("fps", DEFAULT_FPS),
        output=output,
        max_dimension=pick("max_dimension", DEFAULT_MAX_DIMENSION),
    )


def _resolve_duration_pair(
    cli_overrides: dict, build_table: dict
) -> tuple[float | None, float | None]:
    cli_d = cli_overrides.get("duration_per_image")
    cli_t = cli_overrides.get("total_duration")
    if cli_d is not None or cli_t is not None:
        return cli_d, cli_t

    cfg_d = build_table.get("duration_per_image")
    cfg_t = build_table.get("total_duration")
    if cfg_d is not None and cfg_t is not None:
        raise ValueError(
            "config file cannot set both duration_per_image and total_duration"
        )
    if cfg_d is not None or cfg_t is not None:
        return cfg_d, cfg_t

    return None, DEFAULT_TOTAL_DURATION


def segment_table(raw_config: dict) -> list[dict]:
    return raw_config.get("segment", [])
