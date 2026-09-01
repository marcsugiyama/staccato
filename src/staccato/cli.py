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


def _check_dependencies() -> None:
    missing = deps.missing_tools()
    if missing:
        raise click.ClickException(
            f"missing required tool(s) on PATH: {', '.join(missing)}. "
            "See README.md#requirements for install instructions."
        )


@click.group()
@click.version_option(version=__version__, prog_name="staccato")
def cli() -> None:
    """Turn a folder of still images into a timelapse video."""


@cli.command()
@click.argument(
    "input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option(
    "-c", "--config", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option("--duration-per-image", type=float, default=None)
@click.option("--total-duration", type=float, default=None)
@click.option("--transition-duration", type=float, default=None)
@click.option("--transition", type=TRANSITION, default=None)
@click.option(
    "--order", type=click.Choice(["timestamp", "filename"]), default=None
)
@click.option("--fps", type=int, default=None)
@click.option(
    "--max-dimension",
    type=int,
    default=None,
    help="Cap the longer output edge, in pixels (0 = uncapped). Default: 1920.",
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
    )
    click.echo(f"Wrote {options.output}")


@cli.command()
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
