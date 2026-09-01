"""Shared fixtures: the repo's samples/ and tests/fixtures/ directories,
and a skip guard for tests that need real ffmpeg/ffprobe/exiftool on
PATH."""

from __future__ import annotations

from pathlib import Path

import pytest

from staccato import deps

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "samples"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

requires_tools = pytest.mark.skipif(
    deps.missing_tools() != [],
    reason=f"missing required tool(s): {', '.join(deps.missing_tools())}",
)


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES_DIR


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR
