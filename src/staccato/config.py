"""Loads staccato.toml and merges it with CLI overrides into a BuildOptions,
per the CLI-flag > config-file > built-in-default precedence rule."""

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
DEFAULT_CRF = 23
DEFAULT_PRESET = "medium"
DEFAULT_ALIGN_MAX_DIMENSION = 1920
DEFAULT_WARP = "euclidean"
DEFAULT_ALIGN_METHOD = "ecc"
DEFAULT_CROP = True

WARP_CHOICES = ("euclidean", "affine")

PRESET_CHOICES = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow", "placebo",
)

# x264's CRF is roughly logarithmic: +6 ~ half the bitrate/file size,
# -6 ~ double it (content-dependent rule of thumb, not exact). Named
# "size" rather than "quality" so the dial reads as "smaller/larger file"
# -- crf is the mechanism, not the concept a user is choosing between.
SIZE_LEVELS = {
    "smallest": DEFAULT_CRF + 12,
    "smaller": DEFAULT_CRF + 6,
    "default": DEFAULT_CRF,
    "larger": DEFAULT_CRF - 6,
    "largest": DEFAULT_CRF - 12,
}


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
    crf: int
    preset: str


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

    crf = _resolve_crf(cli_overrides, build_table)
    if not (0 <= crf <= 51):
        raise ValueError(f"crf must be between 0 and 51, got {crf}")

    preset = pick("preset", DEFAULT_PRESET)
    if preset not in PRESET_CHOICES:
        raise ValueError(
            f"invalid preset: {preset!r}; choose from {', '.join(PRESET_CHOICES)}"
        )

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
        crf=crf,
        preset=preset,
    )


def _resolve_crf(cli_overrides: dict, build_table: dict) -> int:
    """--crf and --size are two ways to land on the same underlying value;
    --size just looks up a preset crf. Mirrors _resolve_duration_pair's
    precedence: CLI (whichever of the pair was given) beats the config
    file's pair (which may not set both)."""
    cli_crf = cli_overrides.get("crf")
    cli_size = cli_overrides.get("size")
    if cli_crf is not None:
        return cli_crf
    if cli_size is not None:
        return SIZE_LEVELS[cli_size]

    cfg_crf = build_table.get("crf")
    cfg_size = build_table.get("size")
    if cfg_crf is not None and cfg_size is not None:
        raise ValueError("config file cannot set both crf and size")
    if cfg_crf is not None:
        return cfg_crf
    if cfg_size is not None:
        if cfg_size not in SIZE_LEVELS:
            raise ValueError(
                f"invalid size: {cfg_size!r}; choose from {', '.join(SIZE_LEVELS)}"
            )
        return SIZE_LEVELS[cfg_size]

    return DEFAULT_CRF


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


@dataclass
class AlignOptions:
    max_dimension: int
    warp: str
    method: str
    crop: bool
    output: Path


def resolve_align_options(cli_overrides: dict, raw_config: dict, default_output: Path) -> AlignOptions:
    """Merge precedence: CLI flags > config file [align] table > defaults.
    Mirrors resolve_build_options's pattern."""
    align_table = raw_config.get("align", {})

    def pick(key, default):
        if cli_overrides.get(key) is not None:
            return cli_overrides[key]
        if key in align_table:
            return align_table[key]
        return default

    warp = pick("warp", DEFAULT_WARP)
    if warp not in WARP_CHOICES:
        raise ValueError(f"invalid warp: {warp!r}; choose from {', '.join(WARP_CHOICES)}")

    method = pick("method", DEFAULT_ALIGN_METHOD)
    if method != "ecc":
        raise ValueError(f"invalid align method: {method!r}; only 'ecc' is supported")

    output = pick("output", default_output)
    if not isinstance(output, Path):
        output = Path(output)

    return AlignOptions(
        max_dimension=pick("max_dimension", DEFAULT_ALIGN_MAX_DIMENSION),
        warp=warp,
        method=method,
        crop=pick("crop", DEFAULT_CROP),
        output=output,
    )
