"""Unit tests for staccato.cache: deterministic keying and the
get-or-create-with-atomic-rename behavior. No real ffmpeg involved --
`compute` is a fake that just writes a marker file."""

from __future__ import annotations

import os

import pytest

from staccato import cache


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("STACCATO_CACHE_DIR", str(tmp_path / "cache"))


def touch(tmp_path, name="a.jpg"):
    p = tmp_path / name
    p.write_bytes(b"content")
    return p


def test_cache_dir_respects_env_override(tmp_path, monkeypatch):
    override = tmp_path / "custom"
    monkeypatch.setenv("STACCATO_CACHE_DIR", str(override))
    assert cache.cache_dir() == override / "frames"
    assert cache.cache_dir().is_dir()


def test_path_for_is_deterministic(tmp_path):
    src = touch(tmp_path)
    assert cache.path_for(src, 100, 200) == cache.path_for(src, 100, 200)


def test_path_for_differs_by_dimensions(tmp_path):
    src = touch(tmp_path)
    assert cache.path_for(src, 100, 200) != cache.path_for(src, 100, 201)


def test_path_for_differs_when_mtime_changes(tmp_path):
    src = touch(tmp_path)
    before = cache.path_for(src, 100, 200)
    os.utime(src, (0, 0))
    after = cache.path_for(src, 100, 200)
    assert before != after


def test_get_or_create_computes_once_then_reuses(tmp_path):
    src = touch(tmp_path)
    calls = []

    def fake_compute(s, dst, w, h):
        calls.append((s, w, h))
        dst.write_bytes(b"fake-png")

    first = cache.get_or_create(src, 100, 200, fake_compute)
    second = cache.get_or_create(src, 100, 200, fake_compute)

    assert first == second
    assert first.read_bytes() == b"fake-png"
    assert len(calls) == 1  # not recomputed on the second call


def test_get_or_create_leaves_no_temp_files_behind(tmp_path):
    src = touch(tmp_path)

    def fake_compute(s, dst, w, h):
        dst.write_bytes(b"fake-png")

    result = cache.get_or_create(src, 100, 200, fake_compute)
    siblings = list(result.parent.iterdir())
    assert siblings == [result]
