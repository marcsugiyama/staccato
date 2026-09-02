"""Command-line entry point: argument parsing, config/CLI merging, and
orchestration for the `build` and `align` subcommands."""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__, deps
from .config import load_raw_config, resolve_build_options, segment_table
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
) -> None:
    """Assemble a timelapse video from the images in INPUT_DIR."""
    if duration_per_image is not None and total_duration is not None:
        raise click.UsageError(
            "--duration-per-image and --total-duration are mutually exclusive."
        )

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
    )
    click.echo(f"Wrote {options.output}")


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.argument(
    "input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option(
    "-c", "--config", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def align(input_dir: Path, config: Path | None) -> None:
    """Correct frame-to-frame drift in images shot from roughly the same position.

    Not yet implemented — see README.md#roadmap.
    """
    raise click.ClickException("align is not yet implemented; see README.md#roadmap")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
