from __future__ import annotations

import shutil
from pathlib import Path

import click

from . import __version__

KNOWN_TRANSITIONS = {
    "cut",
    "fade",
    "fadeblack",
    "fadewhite",
    "wipe-left",
    "wipe-right",
    "wipe-up",
    "wipe-down",
    "slide-left",
    "slide-right",
    "slide-up",
    "slide-down",
    "circleopen",
    "circleclose",
    "pixelize",
    "random",
}

REQUIRED_TOOLS = ("ffmpeg", "exiftool")


class TransitionType(click.ParamType):
    name = "transition"

    def convert(self, value, param, ctx):
        if value in KNOWN_TRANSITIONS or value.startswith("raw:"):
            return value
        self.fail(
            f"{value!r} is not a known transition. Use one of "
            f"{', '.join(sorted(KNOWN_TRANSITIONS))}, or raw:<xfade-name>.",
            param,
            ctx,
        )


TRANSITION = TransitionType()


def check_dependencies() -> None:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
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
@click.option(
    "-o", "--output", type=click.Path(path_type=Path), default=Path("timelapse.mp4")
)
@click.option(
    "-c", "--config", type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option("--duration-per-image", type=float)
@click.option("--total-duration", type=float)
@click.option("--transition-duration", type=float, default=0.1)
@click.option("--transition", type=TRANSITION, default="fade")
@click.option(
    "--order", type=click.Choice(["timestamp", "filename"]), default="timestamp"
)
@click.option("--fps", type=int, default=30)
def build(
    input_dir: Path,
    output: Path,
    config: Path | None,
    duration_per_image: float | None,
    total_duration: float | None,
    transition_duration: float,
    transition: str,
    order: str,
    fps: int,
) -> None:
    """Assemble a timelapse video from the images in INPUT_DIR."""
    if duration_per_image is not None and total_duration is not None:
        raise click.UsageError(
            "--duration-per-image and --total-duration are mutually exclusive."
        )

    check_dependencies()

    if config is None:
        default_config = input_dir / "staccato.toml"
        if default_config.exists():
            config = default_config

    if duration_per_image is None and total_duration is None:
        total_duration = 120.0

    click.echo("build: not yet implemented. Resolved options:")
    click.echo(f"  input_dir           = {input_dir}")
    click.echo(f"  output              = {output}")
    click.echo(f"  config              = {config}")
    click.echo(f"  duration_per_image  = {duration_per_image}")
    click.echo(f"  total_duration      = {total_duration}")
    click.echo(f"  transition_duration = {transition_duration}")
    click.echo(f"  transition          = {transition}")
    click.echo(f"  order               = {order}")
    click.echo(f"  fps                 = {fps}")


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
