from __future__ import annotations


def derive_duration_per_image(
    total_duration: float,
    fixed_duration_sum: float,
    num_default_segments: int,
    transition_duration: float,
    num_junctions: int,
) -> float:
    """Solve for the per-image duration of segments that don't specify
    their own, given a target total duration, the durations already fixed
    by video clips / per-segment overrides, and the nominal transition
    duration at each junction (overlapping, not additive)."""
    if num_default_segments <= 0:
        raise ValueError("no segments need a derived duration")
    d = (
        total_duration - fixed_duration_sum + num_junctions * transition_duration
    ) / num_default_segments
    if d <= 0:
        raise ValueError(
            f"total_duration={total_duration}s is too short given fixed/override "
            f"durations ({fixed_duration_sum}s) and {num_junctions} transition(s); "
            f"derived duration_per_image would be {d:.3f}s"
        )
    return d


def compute_offsets(
    durations: list[float], transition_durations: list[float]
) -> tuple[list[float], float]:
    """Given N clip durations and N-1 junction transition durations, return
    the xfade `offset` for each junction plus the total output duration.

    xfade offsets overlap adjacent clips rather than adding time: each
    junction's offset is the running combined length minus that junction's
    transition duration.
    """
    if not durations:
        raise ValueError("need at least one segment")
    if len(transition_durations) != len(durations) - 1:
        raise ValueError("need exactly one transition duration per junction")
    length = durations[0]
    offsets: list[float] = []
    for d, t in zip(durations[1:], transition_durations):
        offset = length - t
        offsets.append(offset)
        length = offset + d
    return offsets, length
