"""Tests for staccato.align. Requires the optional `align` extra
(opencv-python-headless, numpy) -- the whole file is skipped if cv2 isn't
importable. Some tests additionally need ffmpeg/exiftool (real
normalize/EXIF work) and are marked `integration`."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from staccato import align, cache, deps  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"

_missing = deps.missing_tools()
requires_tools = pytest.mark.skipif(
    _missing != [], reason=f"missing required tool(s): {', '.join(_missing)}"
)


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STACCATO_CACHE_DIR", str(tmp_path / "cache"))


def touch(dir_: Path, name: str) -> Path:
    p = dir_ / name
    p.write_bytes(b"")
    return p


# --- ECC correctness -------------------------------------------------

def test_estimate_transform_recovers_a_known_synthetic_shift():
    img = cv2.imread(str(SAMPLES_DIR / "PIA00342.jpg"), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]

    known = cv2.getRotationMatrix2D((w / 2, h / 2), 3.0, 1.0)
    known[0, 2] += 15.0
    known[1, 2] += -8.0
    shifted = cv2.warpAffine(img, known, (w, h), flags=cv2.INTER_LINEAR)

    template_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype("float32")
    input_gray = cv2.cvtColor(shifted, cv2.COLOR_BGR2GRAY).astype("float32")

    matrix, correlation = align.estimate_transform(template_gray, input_gray, "euclidean")

    assert correlation > 0.99
    np.testing.assert_allclose(matrix, known, atol=0.5)

    recovered = align.apply_transform(shifted, matrix, w, h)
    error_after = np.abs(recovered.astype("float32") - img.astype("float32")).mean()
    error_before = np.abs(shifted.astype("float32") - img.astype("float32")).mean()
    assert error_after < error_before / 5


def test_estimate_transform_raises_alignment_error_on_bad_input():
    rng = np.random.default_rng(0)
    noise_a = rng.integers(0, 255, (200, 200), dtype=np.uint8).astype("float32")
    noise_b = rng.integers(0, 255, (200, 200), dtype=np.uint8).astype("float32")
    with pytest.raises(align.AlignmentError):
        align.estimate_transform(noise_a, noise_b, "euclidean", max_iterations=5, eps=1e-9)


# --- resolve_groups ----------------------------------------------------

def test_resolve_groups_explicit_requires_key_and_images(tmp_path):
    touch(tmp_path, "a.jpg")
    with pytest.raises(ValueError, match="key.*images"):
        align.resolve_groups(tmp_path, {"align": {"group": [{"key": "a.jpg"}]}})


def test_resolve_groups_explicit_key_must_be_first_in_images(tmp_path):
    touch(tmp_path, "a.jpg")
    touch(tmp_path, "b.jpg")
    raw = {"align": {"group": [{"key": "b.jpg", "images": ["a.jpg", "b.jpg"]}]}}
    with pytest.raises(ValueError, match="first entry"):
        align.resolve_groups(tmp_path, raw)


def test_resolve_groups_explicit_missing_file_raises(tmp_path):
    touch(tmp_path, "a.jpg")
    raw = {"align": {"group": [{"key": "a.jpg", "images": ["a.jpg", "missing.jpg"]}]}}
    with pytest.raises(ValueError, match="missing.jpg"):
        align.resolve_groups(tmp_path, raw)


def test_resolve_groups_explicit_happy_path(tmp_path):
    a, b, c = touch(tmp_path, "a.jpg"), touch(tmp_path, "b.jpg"), touch(tmp_path, "c.jpg")
    raw = {
        "align": {
            "group": [
                {"key": "a.jpg", "images": ["a.jpg", "b.jpg"]},
                {"key": "c.jpg", "images": ["c.jpg"]},
            ]
        }
    }
    groups = align.resolve_groups(tmp_path, raw)
    assert [g.name for g in groups] == ["group-1", "group-2"]
    assert groups[0].key == a
    assert groups[0].images == [a, b]
    assert groups[1].images == [c]


@requires_tools
def test_resolve_groups_implicit_default_is_one_chronological_group(tmp_path):
    for f in sorted(SAMPLES_DIR.glob("*.jpg")):
        shutil.copy(f, tmp_path / f.name)
    groups = align.resolve_groups(tmp_path, {})
    assert len(groups) == 1
    assert groups[0].key == groups[0].images[0]
    assert len(groups[0].images) == len(list(SAMPLES_DIR.glob("*.jpg")))


def test_resolve_groups_implicit_no_images_raises(tmp_path):
    with pytest.raises(ValueError, match="no images found"):
        align.resolve_groups(tmp_path, {})


# --- chain key -----------------------------------------------------

def test_chain_key_stable_for_identical_inputs(tmp_path):
    a, b = touch(tmp_path, "a.jpg"), touch(tmp_path, "b.jpg")
    group = align.ResolvedGroup(name="g", key=a, images=[a, b])
    k1 = align._chain_key(group, 1, "euclidean", "ecc", 1920)
    k2 = align._chain_key(group, 1, "euclidean", "ecc", 1920)
    assert k1 == k2


def test_chain_key_changes_when_an_earlier_image_in_the_chain_changes(tmp_path):
    import os
    import time

    a, b = touch(tmp_path, "a.jpg"), touch(tmp_path, "b.jpg")
    group = align.ResolvedGroup(name="g", key=a, images=[a, b])
    before = align._chain_key(group, 1, "euclidean", "ecc", 1920)

    time.sleep(0.01)
    a.write_bytes(b"different content")
    os.utime(a, None)

    after = align._chain_key(group, 1, "euclidean", "ecc", 1920)
    assert before != after


def test_chain_key_changes_with_warp_model(tmp_path):
    a, b = touch(tmp_path, "a.jpg"), touch(tmp_path, "b.jpg")
    group = align.ResolvedGroup(name="g", key=a, images=[a, b])
    k_euclidean = align._chain_key(group, 1, "euclidean", "ecc", 1920)
    k_affine = align._chain_key(group, 1, "affine", "ecc", 1920)
    assert k_euclidean != k_affine


# --- align_group end-to-end --------------------------------------------

@requires_tools
def test_align_group_writes_sequence_numbered_output_with_exif(tmp_path):
    files = sorted(SAMPLES_DIR.glob("*.jpg"))[:3]
    group = align.ResolvedGroup(name="group-1", key=files[0], images=files)
    out_dir = tmp_path / "aligned"

    results = align.align_group(group, out_dir, 400, "euclidean", True, True)

    assert len(results) == 3
    assert all(r.output.exists() for r in results)
    names = sorted(p.name for p in out_dir.glob("*.png"))
    assert names[0].startswith("1_") or names[0].startswith("01_")

    import subprocess
    for r in results:
        info = subprocess.run(
            ["exiftool", "-DateTimeOriginal", "-s3", str(r.output)],
            capture_output=True, text=True,
        )
        assert info.stdout.strip(), f"no DateTimeOriginal copied to {r.output}"


@requires_tools
def test_align_group_crop_shrinks_frame_vs_no_crop(tmp_path):
    files = sorted(SAMPLES_DIR.glob("*.jpg"))[:2]
    group = align.ResolvedGroup(name="group-1", key=files[0], images=files)

    cropped = align.align_group(group, tmp_path / "cropped", 300, "euclidean", True, True)
    uncropped = align.align_group(group, tmp_path / "uncropped", 300, "euclidean", False, True)

    cropped_dims = cv2.imread(str(cropped[0].output)).shape[:2]
    uncropped_dims = cv2.imread(str(uncropped[0].output)).shape[:2]
    assert cropped_dims[0] <= uncropped_dims[0]
    assert cropped_dims[1] <= uncropped_dims[1]


@requires_tools
def test_align_group_caches_transforms_across_runs(tmp_path, monkeypatch):
    files = sorted(SAMPLES_DIR.glob("*.jpg"))[:3]
    group = align.ResolvedGroup(name="group-1", key=files[0], images=files)

    calls = []
    real_estimate = align.estimate_transform

    def counting_estimate(*args, **kwargs):
        calls.append(1)
        return real_estimate(*args, **kwargs)

    monkeypatch.setattr(align, "estimate_transform", counting_estimate)

    align.align_group(group, tmp_path / "out1", 300, "euclidean", True, True)
    first_run_calls = len(calls)
    assert first_run_calls == 2  # one ECC call per non-key image

    align.align_group(group, tmp_path / "out2", 300, "euclidean", True, True)
    assert len(calls) == first_run_calls  # second run: fully cached, no new ECC calls


@requires_tools
def test_align_group_failure_does_not_advance_anchor(tmp_path, monkeypatch):
    files = sorted(SAMPLES_DIR.glob("*.jpg"))[:3]
    group = align.ResolvedGroup(name="group-1", key=files[0], images=files)

    seen_templates = []
    real_estimate = align.estimate_transform

    def flaky_estimate(template, input_, warp, *a, **kw):
        seen_templates.append(template.copy())
        if len(seen_templates) == 1:
            raise align.AlignmentError("simulated non-convergence")
        return real_estimate(template, input_, warp, *a, **kw)

    monkeypatch.setattr(align, "estimate_transform", flaky_estimate)

    results = align.align_group(group, tmp_path / "out", 300, "euclidean", True, False)

    assert results[1].succeeded is False
    assert results[2].succeeded is True
    # image[2]'s template must be byte-for-byte the same array as image[1]'s
    # (both the key's own gray frame) -- proof the anchor didn't advance
    # past the key after image[1]'s failure, rather than silently
    # comparing image[2] against image[1]'s unverified output.
    assert len(seen_templates) == 2
    np.testing.assert_array_equal(seen_templates[0], seen_templates[1])


def test_align_requires_extra_when_cv2_missing(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from staccato.cli import cli

    monkeypatch.setattr("staccato.deps.missing_tools", lambda: [])
    monkeypatch.setitem(sys.modules, "cv2", None)

    runner = CliRunner()
    result = runner.invoke(cli, ["align", str(tmp_path)])
    assert result.exit_code != 0
    assert "pip install staccato[align]" in result.output
