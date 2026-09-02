"""ECC-based sequential image alignment ("staccato align"). See
ARCHITECTURE.md#staccato-align for the full design and rationale --
sequential chaining within groups, why ECC over feature-matching, why
Euclidean is the default warp model, the transform-caching split, and
the output contract that lets aligned output feed straight into
`staccato build`.

cv2/numpy are imported lazily throughout this module: they're part of
the optional `align` extra, not a dependency of plain `build` usage.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import cache
from .exif import read_capture_times
from .ffmpeg_pipeline import clamp_to_max_dimension, normalize_image, probe_dimensions
from .sequence import IMAGE_EXTENSIONS, scan_base_files

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

WARP_MODEL_NAMES = ("euclidean", "affine")


class AlignmentError(Exception):
    """Raised when ECC fails to converge for a pair."""


@dataclass
class ResolvedGroup:
    name: str
    key: Path
    images: list[Path]  # includes key as images[0], remaining in chain order


@dataclass
class AlignedImage:
    source: Path
    output: Path
    correlation: float | None  # ECC's confidence score; unknown (None) doesn't imply failure
    succeeded: bool  # False only when ECC actually failed to converge for this image


def resolve_groups(input_dir: Path, raw_config: dict) -> list[ResolvedGroup]:
    align_table = raw_config.get("align", {})
    group_configs = align_table.get("group", [])

    if group_configs:
        groups = []
        for i, g in enumerate(group_configs):
            key_name = g.get("key")
            image_names = g.get("images")
            if not key_name or not image_names:
                raise ValueError(f"align.group[{i}]: both 'key' and 'images' are required")
            if image_names[0] != key_name:
                raise ValueError(
                    f"align.group[{i}]: 'key' ({key_name!r}) must be the first entry in 'images'"
                )
            paths = [input_dir / name for name in image_names]
            missing = [p.name for p in paths if not p.exists()]
            if missing:
                raise ValueError(
                    f"align.group[{i}]: missing file(s): {', '.join(missing)}"
                )
            groups.append(ResolvedGroup(name=f"group-{i + 1}", key=paths[0], images=paths))
        return groups

    # No config: one implicit group spanning every image, chronological,
    # keyed on the earliest -- viable specifically because chaining means
    # no image needs to resemble a reference from months away, only its
    # immediate predecessor.
    ordered = scan_base_files(input_dir, "timestamp", None)
    if not ordered:
        raise ValueError(f"no images found in {input_dir}")
    return [ResolvedGroup(name="group-1", key=ordered[0], images=ordered)]


def _chain_key(
    group: ResolvedGroup, upto_index: int, warp: str, method: str, max_dimension: int
) -> str:
    """Hash of the whole prefix from the group's key through images[upto_index]
    (inclusive), plus the parameters that affect ECC's result. Identical key =>
    identical result, since alignment at image i depends on everything before
    it in its chain. Touching an early image invalidates every cached
    transform downstream of it, which is correct: drift is chain-dependent."""
    parts = [f"warp={warp}", f"method={method}", f"max_dimension={max_dimension}"]
    for p in group.images[: upto_index + 1]:
        st = p.stat()
        parts.append(f"{p.resolve()}|{st.st_mtime_ns}|{st.st_size}")
    return "|".join(parts)


def _load_gray_f32(path: Path) -> "np.ndarray":
    import cv2

    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"failed to read image: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype("float32")


def estimate_transform(
    template_gray: "np.ndarray",
    input_gray: "np.ndarray",
    warp: str,
    max_iterations: int = 1000,
    eps: float = 1e-6,
) -> tuple["np.ndarray", float]:
    """Estimate the warp that maps input_gray into template_gray's frame.
    Returns (2x3 warp matrix, correlation coefficient in [-1, 1] -- higher
    is a better match). Raises AlignmentError if ECC doesn't converge."""
    import cv2
    import numpy as np

    motion_type = {"euclidean": cv2.MOTION_EUCLIDEAN, "affine": cv2.MOTION_AFFINE}[warp]
    warp_matrix = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, max_iterations, eps)
    try:
        correlation, warp_matrix = cv2.findTransformECC(
            template_gray, input_gray, warp_matrix, motion_type, criteria
        )
    except cv2.error as exc:
        raise AlignmentError(str(exc)) from exc
    return warp_matrix, correlation


def apply_transform(img: "np.ndarray", warp_matrix: "np.ndarray", width: int, height: int) -> "np.ndarray":
    """Warp img (in its own original pixel space) directly into the
    group's key frame using its cumulative transform. Always applied once
    to original pixels -- never to an already-warped image -- so
    resampling blur can't compound across a chain."""
    import cv2

    return cv2.warpAffine(
        img, warp_matrix, (width, height),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
    )


def _identity_matrix() -> "np.ndarray":
    import numpy as np

    return np.eye(2, 3, dtype=np.float32)


def _valid_rect(warp_matrix: "np.ndarray", src_w: int, src_h: int, dst_w: int, dst_h: int):
    """The axis-aligned rectangle, in the destination (key) frame, that's
    guaranteed covered by real (non-border) warped pixels -- i.e. the
    image of the source frame's corners under the transform, intersected
    with the destination canvas."""
    import cv2
    import numpy as np

    corners = np.array(
        [[0, 0], [src_w, 0], [src_w, src_h], [0, src_h]], dtype=np.float32
    ).reshape(-1, 1, 2)
    mapped = cv2.transform(corners, warp_matrix).reshape(-1, 2)
    x0, y0 = mapped[:, 0].min(), mapped[:, 1].min()
    x1, y1 = mapped[:, 0].max(), mapped[:, 1].max()
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(float(dst_w), x1), min(float(dst_h), y1)
    return x0, y0, x1, y1


def align_group(
    group: ResolvedGroup,
    output_dir: Path,
    max_dimension: int,
    warp: str,
    crop: bool,
    use_cache: bool,
    method: str = "ecc",
) -> list[AlignedImage]:
    if warp not in WARP_MODEL_NAMES:
        raise ValueError(f"unknown warp model: {warp!r}; choose from {WARP_MODEL_NAMES}")
    if method != "ecc":
        raise ValueError(f"unknown align method: {method!r}; only 'ecc' is supported")

    normalize = cache.get_or_create if use_cache else _normalize_uncached

    key_native_png = normalize(group.key, None, None, normalize_image)
    native_w, native_h = probe_dimensions(key_native_png)
    width, height = clamp_to_max_dimension(native_w, native_h, max_dimension)

    normalized = [normalize(p, width, height, normalize_image) for p in group.images]

    results: list[AlignedImage] = []
    aligned_arrays: list["np.ndarray"] = []
    valid_rects = []
    last_good_gray = None
    last_good_matrix = _identity_matrix()

    for i, (src, png) in enumerate(zip(group.images, normalized)):
        import cv2

        color = cv2.imread(str(png), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY).astype("float32")

        if i == 0:
            matrix, correlation, succeeded = _identity_matrix(), None, True
        else:
            chain_key = _chain_key(group, i, warp, method, max_dimension)
            # Only the (tiny) matrix is cached, not the correlation score --
            # so on a cache hit we don't have a fresh score to report.
            # correlation_holder captures it as a side effect on a miss,
            # when estimate_transform actually runs.
            correlation_holder: list[float] = []

            def compute(_template=last_good_gray, _input=gray, _warp=warp):
                m, corr = estimate_transform(_template, _input, _warp)
                correlation_holder.append(corr)
                return m

            try:
                matrix = cache.get_or_compute_transform(chain_key, compute)
                correlation = correlation_holder[0] if correlation_holder else None
                succeeded = True
            except AlignmentError as exc:
                logger.warning(
                    "align: %s failed to converge against its predecessor (%s); "
                    "passing through unaligned and keeping the last known-good anchor",
                    src.name, exc,
                )
                matrix, correlation, succeeded = last_good_matrix, None, False

        warped = apply_transform(color, matrix, width, height)
        aligned_arrays.append(warped)
        valid_rects.append(_valid_rect(matrix, width, height, width, height))

        if succeeded:
            last_good_gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY).astype("float32")
            last_good_matrix = matrix
        # on failure, last_good_gray/matrix intentionally left unadvanced,
        # so the next image compares against the last known-good frame
        # rather than inheriting this one's failure.

        results.append(
            AlignedImage(source=src, output=Path(), correlation=correlation, succeeded=succeeded)
        )

    if crop:
        x0 = max(r[0] for r in valid_rects)
        y0 = max(r[1] for r in valid_rects)
        x1 = min(r[2] for r in valid_rects)
        y1 = min(r[3] for r in valid_rects)
        if x1 <= x0 or y1 <= y0:
            raise ValueError(
                f"{group.name}: no common region survives cropping -- images have "
                "drifted too far apart, or too few frames overlap. Try --no-crop, "
                "a different warp model, or splitting into more groups."
            )
        box = (int(x0), int(y0), int(x1), int(y1))
    else:
        box = None

    output_dir.mkdir(parents=True, exist_ok=True)
    width_digits = len(str(len(group.images)))
    for i, (arr, result) in enumerate(zip(aligned_arrays, results)):
        import cv2

        if box is not None:
            x0, y0, x1, y1 = box
            arr = arr[y0:y1, x0:x1]
        seq = str(i + 1).zfill(width_digits)
        out_path = output_dir / f"{seq}_{result.source.stem}.png"
        cv2.imwrite(str(out_path), arr)
        _copy_exif(result.source, out_path)
        result.output = out_path

    return results


def _normalize_uncached(src: Path, width: int | None, height: int | None, compute) -> Path:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="staccato-align-")) / f"{src.stem}.png"
    compute(src, tmp, width, height)
    return tmp


def _copy_exif(source: Path, output_png: Path) -> None:
    """Best-effort: copy DateTimeOriginal so `build`'s order = "timestamp"
    keeps working on aligned output. Not required for correctness --
    output filenames are already sequence-numbered in chain order, so
    order = "filename" works regardless of whether this succeeds."""
    result = subprocess.run(
        [
            "exiftool", "-overwrite_original", "-TagsFromFile", str(source),
            "-DateTimeOriginal", str(output_png),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "align: could not copy EXIF timestamp from %s to %s: %s",
            source.name, output_png.name, result.stderr.strip(),
        )
