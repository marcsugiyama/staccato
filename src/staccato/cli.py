"""Command-line entry point: argument parsing, config/CLI merging, and
orchestration for the `build` and `align` subcommands."""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__, deps
from .config import (
    PRESET_CHOICES,
    SIZE_LEVELS,
    WARP_CHOICES,
    load_raw_config,
    resolve_align_options,
    resolve_build_options,
    segment_table,
)
from .ffmpeg_pipeline import build_video, probe_duration
from .sequence import apply_segment_overrides, resolve_durations, scan_base_files
from .transitions import is_valid as is_valid_transition


class TransitionType(click.ParamType):
    name = "transition"

    def convert(self, value, param, ctx):
        if is_valid_transition(value):
            return value
        self.fail(
            f"{value!r} is not a known transition. See README.md#transitions "
            "for the full list, or use raw:<xfade-name>.",
            param,
            ctx,
        )


TRANSITION = TransitionType()

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _check_dependencies() -> None:
    missing = deps.missing_tools()
    if missing:
        raise click.ClickException(
            f"missing required tool(s) on PATH: {', '.join(missing)}. "
            "See README.md#requirements for install instructions."
        )


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__, prog_name="staccato")
def cli() -> None:
    """Turn a folder of still images into a timelapse video."""


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument(
    "input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), default=None,
    help="Output video path. Default: timelapse.mp4.",
)
@click.option(
    "-c", "--config", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Config file. Default: <input-dir>/staccato.toml, if present.",
)
@click.option(
    "--duration-per-image", type=float, default=None,
    help="Seconds each image is shown. Mutually exclusive with --total-duration.",
)
@click.option(
    "--total-duration", type=float, default=None,
    help="Target total video length in seconds; per-image duration is derived. "
    "Mutually exclusive with --duration-per-image. Default: 120.",
)
@click.option(
    "--transition-duration", type=float, default=None,
    help="Crossfade length in seconds, overlapping adjacent images. Default: 0.1.",
)
@click.option(
    "--transition", type=TRANSITION, default=None,
    help="Transition style: fade (default), cut, fadeblack, fadewhite, "
    "wipe-{left,right,up,down}, slide-{left,right,up,down}, circleopen, "
    "circleclose, pixelize, random, or raw:<xfade-name>.",
)
@click.option(
    "--order", type=click.Choice(["timestamp", "filename"]), default=None,
    help="Ordering mode. Default: timestamp. (explicit is config-file-only.)",
)
@click.option(
    "--fps", type=int, default=None, help="Output frame rate. Default: 30."
)
@click.option(
    "--max-dimension",
    type=int,
    default=None,
    help="Cap the longer output edge, in pixels (0 = uncapped). Default: 1920.",
)
@click.option(
    "--cache/--no-cache",
    default=True,
    help="Cache normalized frames, keyed by source file identity and "
    "--max-dimension, so re-running with only transition/timing changes "
    "skips re-decoding images. Cache lives under ~/.cache/staccato "
    "(override with $STACCATO_CACHE_DIR). --no-cache neither reads nor "
    "writes it.",
)
@click.option(
    "--crf", type=click.IntRange(0, 51), default=None,
    help="libx264 quality factor: 0=lossless, 51=worst. Lower = larger file. "
    "Default: 23. Mutually exclusive with --size.",
)
@click.option(
    "--size", type=click.Choice(list(SIZE_LEVELS)), default=None,
    help="Shortcut for --crf, framed by output file size rather than a "
    "quality number: " + ", ".join(f"{k}={v}" for k, v in SIZE_LEVELS.items())
    + ". Each step is roughly a halving/doubling of file size (content-"
    "dependent). Mutually exclusive with --crf.",
)
@click.option(
    "--preset", type=click.Choice(PRESET_CHOICES), default=None,
    help="libx264 encoder effort: slower presets compress better at the "
    "same --crf, at the cost of encode time. Default: medium.",
)
def build(
    input_dir: Path,
    output: Path | None,
    config: Path | None,
    duration_per_image: float | None,
    total_duration: float | None,
    transition_duration: float | None,
    transition: str | None,
    order: str | None,
    fps: int | None,
    max_dimension: int | None,
    cache: bool,
    crf: int | None,
    size: str | None,
    preset: str | None,
) -> None:
    """Assemble a timelapse video from the images in INPUT_DIR."""
    if duration_per_image is not None and total_duration is not None:
        raise click.UsageError(
            "--duration-per-image and --total-duration are mutually exclusive."
        )
    if crf is not None and size is not None:
        raise click.UsageError("--crf and --size are mutually exclusive.")

    _check_dependencies()

    if config is None:
        default_config = input_dir / "staccato.toml"
        if default_config.exists():
            config = default_config
    raw_config = load_raw_config(config)

    cli_overrides = dict(
        duration_per_image=duration_per_image,
        total_duration=total_duration,
        transition_duration=transition_duration,
        transition=transition,
        order=order,
        fps=fps,
        output=output,
        max_dimension=max_dimension,
        crf=crf,
        size=size,
        preset=preset,
    )

    try:
        options = resolve_build_options(cli_overrides, raw_config)
        base_files = scan_base_files(input_dir, options.order, options.order_list)
        if not base_files:
            raise ValueError(f"no images found in {input_dir}")
        segments = apply_segment_overrides(
            base_files, input_dir, segment_table(raw_config)
        )
        lengths = resolve_durations(
            segments,
            options.duration_per_image,
            options.total_duration,
            options.transition_duration,
            probe_duration,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Building {len(segments)} segment(s) -> {options.output}")
    build_video(
        segments,
        lengths,
        options.transition_duration,
        options.transition,
        options.random_pool,
        options.fps,
        options.output,
        options.max_dimension,
        cache,
        options.crf,
        options.preset,
    )
    click.echo(f"Wrote {options.output}")


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument(
    "input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), default=None,
    help="Output directory for aligned images. Default: ./aligned.",
)
@click.option(
    "-c", "--config", type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Config file. Default: <input-dir>/staccato.toml, if present.",
)
@click.option(
    "--max-dimension", type=int, default=None,
    help="Decode/scale images to this size before aligning -- independent of "
    "build's own --max-dimension. Lower it for a fast preview pass before "
    "committing to a full-resolution run; see ARCHITECTURE.md#staccato-align. "
    "Default: 1920.",
)
@click.option(
    "--warp", type=click.Choice(WARP_CHOICES), default=None,
    help="Warp model: euclidean (default, translation+rotation only) or "
    "affine (+scale/shear -- tolerates more drift but more likely to "
    "misattribute real scene change as camera motion).",
)
@click.option(
    "--crop/--no-crop", default=None,
    help="Crop each group to its common aligned region, removing warp "
    "borders. Default: --crop.",
)
@click.option(
    "--cache/--no-cache", default=True,
    help="Cache ECC transforms, keyed by each image's full chain history "
    "so only what actually changed needs realigning. --no-cache neither "
    "reads nor writes it.",
)
def align(
    input_dir: Path,
    output: Path | None,
    config: Path | None,
    max_dimension: int | None,
    warp: str | None,
    crop: bool | None,
    cache: bool,
) -> None:
    """Correct frame-to-frame drift in images shot from roughly the same position.

    Writes aligned images to --output, which can then be used as ordinary
    input to `staccato build`. See ARCHITECTURE.md#staccato-align for the
    full design (sequential per-group chaining, why Euclidean is the
    default warp model, failure handling, the output contract).
    """
    _check_dependencies()
    try:
        import cv2  # noqa: F401
    except ImportError as exc:
        raise click.ClickException(
            "align requires the optional 'align' extra: pip install staccato[align]"
        ) from exc

    from .align import align_group, resolve_groups

    if config is None:
        default_config = input_dir / "staccato.toml"
        if default_config.exists():
            config = default_config
    raw_config = load_raw_config(config)

    cli_overrides = dict(max_dimension=max_dimension, warp=warp, crop=crop, output=output)

    try:
        options = resolve_align_options(cli_overrides, raw_config, Path("aligned"))
        groups = resolve_groups(input_dir, raw_config)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    total_images = sum(len(g.images) for g in groups)
    click.echo(
        f"Aligning {total_images} image(s) across {len(groups)} group(s) -> {options.output}"
    )

    total_failed = 0
    for group in groups:
        try:
            results = align_group(
                group, options.output, options.max_dimension, options.warp,
                options.crop, cache, options.method,
            )
        except ValueError as exc:
            raise click.ClickException(f"{group.name}: {exc}") from exc
        failed = [r for r in results if not r.succeeded]
        total_failed += len(failed)
        click.echo(f"  {group.name}: {len(results)} image(s), {len(failed)} failed to converge")

    click.echo(f"Wrote {total_images} image(s) to {options.output}")
    if total_failed:
        click.echo(
            f"Warning: {total_failed} image(s) failed to converge and were carried "
            "through with the previous frame's alignment. See the warnings above "
            "for which files."
        )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
