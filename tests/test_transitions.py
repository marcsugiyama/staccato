"""Unit tests for staccato.transitions: schema-name validation and
resolution of cut/random/raw values into concrete xfade parameters."""

from __future__ import annotations

import pytest

from staccato import transitions


def test_is_valid_accepts_known_names():
    assert transitions.is_valid("fade")
    assert transitions.is_valid("wipe-left")
    assert transitions.is_valid("cut")
    assert transitions.is_valid("random")


def test_is_valid_accepts_raw_prefix():
    assert transitions.is_valid("raw:distance")


def test_is_valid_rejects_unknown():
    assert not transitions.is_valid("bogus")
    assert not transitions.is_valid("wipeleft")  # ffmpeg name, not schema name


@pytest.mark.parametrize(
    "schema_name,xfade_name",
    [
        ("fade", "fade"),
        ("wipe-left", "wipeleft"),
        ("wipe-right", "wiperight"),
        ("slide-up", "slideup"),
        ("circleopen", "circleopen"),
        ("pixelize", "pixelize"),
    ],
)
def test_resolve_maps_schema_names_to_xfade_names(schema_name, xfade_name):
    name, duration = transitions.resolve(schema_name, 0.25, fps=30, random_pool=None)
    assert name == xfade_name
    assert duration == 0.25


def test_resolve_cut_is_a_single_frame_fade():
    name, duration = transitions.resolve("cut", 1.0, fps=25, random_pool=None)
    assert name == "fade"
    assert duration == pytest.approx(1 / 25)


def test_resolve_raw_passes_name_through_verbatim():
    name, duration = transitions.resolve("raw:distance", 0.4, fps=30, random_pool=None)
    assert name == "distance"
    assert duration == 0.4


def test_resolve_random_picks_from_given_pool():
    name, duration = transitions.resolve(
        "random", 0.2, fps=30, random_pool=["wipe-left"]
    )
    assert name == "wipeleft"
    assert duration == 0.2


def test_resolve_random_defaults_to_all_named_transitions():
    seen = {
        transitions.resolve("random", 0.2, fps=30, random_pool=None)[0]
        for _ in range(200)
    }
    # With 200 draws over a small pool we should see meaningful variety,
    # and never something outside the known xfade names.
    assert seen <= set(transitions.XFADE_NAMES.values())
    assert len(seen) > 1


def test_resolve_unknown_value_raises():
    with pytest.raises(ValueError):
        transitions.resolve("bogus", 0.2, fps=30, random_pool=None)
