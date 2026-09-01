"""Maps staccato's schema-level transition names (e.g. "wipe-left") to
ffmpeg's xfade filter names, and resolves the special "cut", "random", and
"raw:<name>" values into a concrete (name, duration) pair."""

from __future__ import annotations

import random

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

# staccato's schema names (dashed) -> ffmpeg xfade filter names.
XFADE_NAMES = {
    "fade": "fade",
    "fadeblack": "fadeblack",
    "fadewhite": "fadewhite",
    "wipe-left": "wipeleft",
    "wipe-right": "wiperight",
    "wipe-up": "wipeup",
    "wipe-down": "wipedown",
    "slide-left": "slideleft",
    "slide-right": "slideright",
    "slide-up": "slideup",
    "slide-down": "slidedown",
    "circleopen": "circleopen",
    "circleclose": "circleclose",
    "pixelize": "pixelize",
}

RANDOMIZABLE = tuple(XFADE_NAMES.keys())


def is_valid(value: str) -> bool:
    return value in KNOWN_TRANSITIONS or value.startswith("raw:")


def resolve(
    value: str, transition_duration: float, fps: int, random_pool: list[str] | None
) -> tuple[str, float]:
    """Resolve a schema-level transition value into an (xfade filter name,
    duration) pair. 'cut' becomes a single-frame fade, which is visually a
    hard cut without special-casing the filtergraph. 'random' picks from
    random_pool (or all non-cut types) and resolves recursively."""
    if value == "cut":
        return "fade", 1.0 / fps
    if value == "random":
        pool = random_pool or list(RANDOMIZABLE)
        return resolve(random.choice(pool), transition_duration, fps, random_pool)
    if value.startswith("raw:"):
        return value[len("raw:") :], transition_duration
    if value not in XFADE_NAMES:
        raise ValueError(f"unknown transition: {value!r}")
    return XFADE_NAMES[value], transition_duration
