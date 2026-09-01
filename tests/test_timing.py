"""Unit tests for the offset/duration math in staccato.timing."""

from __future__ import annotations

import pytest

from staccato.timing import compute_offsets, derive_duration_per_image


def test_compute_offsets_uniform_matches_hand_verified_ffmpeg_run():
    # 5 clips, 3s each, 1s transitions -- matches the manual ffmpeg test
    # that validated this formula against a real render (offsets 2,4,6,8,
    # total 11s).
    offsets, total = compute_offsets([3, 3, 3, 3, 3], [1, 1, 1, 1])
    assert offsets == [2, 4, 6, 8]
    assert total == 11


def test_compute_offsets_single_segment_has_no_junctions():
    offsets, total = compute_offsets([5.0], [])
    assert offsets == []
    assert total == 5.0


def test_compute_offsets_varying_durations_and_transitions():
    # clip0=2s, clip1=4s (transition 0.5s), clip2=1s (transition 1s)
    offsets, total = compute_offsets([2, 4, 1], [0.5, 1])
    assert offsets == [1.5, 4.5]
    assert total == 5.5


def test_compute_offsets_requires_one_transition_per_junction():
    with pytest.raises(ValueError):
        compute_offsets([1, 2, 3], [0.1])


def test_compute_offsets_requires_at_least_one_segment():
    with pytest.raises(ValueError):
        compute_offsets([], [])


def test_derive_duration_per_image_matches_readme_example():
    # From CONFIG.md/README: total=120s, 179 images, transition=0.1s.
    d = derive_duration_per_image(
        total_duration=120,
        fixed_duration_sum=0,
        num_default_segments=179,
        transition_duration=0.1,
        num_junctions=178,
    )
    assert d == pytest.approx(0.7698, abs=1e-3)


def test_derive_duration_per_image_accounts_for_fixed_segments():
    # 5 slots total, 2 are fixed (video clips totalling 4s), 3 need a
    # derived duration, 4 junctions at 0.2s each, target total 10s.
    d = derive_duration_per_image(
        total_duration=10,
        fixed_duration_sum=4,
        num_default_segments=3,
        transition_duration=0.2,
        num_junctions=4,
    )
    # 10 - 4 + 4*0.2 = 6.8, split across 3 -> 2.2667
    assert d == pytest.approx(6.8 / 3)


def test_derive_duration_per_image_raises_when_result_not_positive():
    with pytest.raises(ValueError):
        derive_duration_per_image(
            total_duration=1,
            fixed_duration_sum=10,
            num_default_segments=2,
            transition_duration=0.1,
            num_junctions=1,
        )


def test_derive_duration_per_image_raises_with_no_default_segments():
    with pytest.raises(ValueError):
        derive_duration_per_image(
            total_duration=10,
            fixed_duration_sum=5,
            num_default_segments=0,
            transition_duration=0.1,
            num_junctions=1,
        )
