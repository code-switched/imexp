"""Tests for packaging metadata in pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_pins_working_tzlocal_version() -> None:
    """Packaging metadata pins the known-good tzlocal wheel."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        data = tomllib.load(handle)

    dependencies = data["project"]["dependencies"]
    assert "tzlocal==5.3.1" in dependencies
