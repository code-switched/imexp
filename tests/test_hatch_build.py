"""Tests for the Hatch build hook."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "packaging" / "hatch_build.py"
INTERFACE_MODULE = types.ModuleType("hatchling.builders.hooks.plugin.interface")
INTERFACE_MODULE.BuildHookInterface = type("BuildHookInterface", (), {})
sys.modules.setdefault("hatchling", types.ModuleType("hatchling"))
sys.modules.setdefault("hatchling.builders", types.ModuleType("hatchling.builders"))
sys.modules.setdefault(
    "hatchling.builders.hooks",
    types.ModuleType("hatchling.builders.hooks"),
)
sys.modules.setdefault(
    "hatchling.builders.hooks.plugin",
    types.ModuleType("hatchling.builders.hooks.plugin"),
)
sys.modules["hatchling.builders.hooks.plugin.interface"] = INTERFACE_MODULE
MODULE_SPEC = importlib.util.spec_from_file_location("imexp_hatch_build", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"could not load hatch build hook from {MODULE_PATH}")
HATCH_BUILD = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(HATCH_BUILD)


def test_parse_macos_arch_accepts_supported_value() -> None:
    """Parse a single supported macOS architecture."""
    assert HATCH_BUILD._parse_macos_arch("x86_64\n") == "x86_64"


def test_parse_macos_arch_rejects_multiple_values() -> None:
    """Reject universal binaries for platform wheel tagging."""
    with pytest.raises(ValueError, match="single macOS architecture"):
        HATCH_BUILD._parse_macos_arch("x86_64 arm64\n")


def test_parse_macos_min_version_supports_legacy_command() -> None:
    """Parse the legacy LC_VERSION_MIN_MACOSX format."""
    output = """
Load command 9
      cmd LC_VERSION_MIN_MACOSX
  cmdsize 16
  version 10.12
      sdk 26.2
"""
    assert HATCH_BUILD._parse_macos_min_version(output) == (10, 12)


def test_parse_macos_min_version_supports_build_version() -> None:
    """Parse the modern LC_BUILD_VERSION format."""
    output = """
Load command 10
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform MACOS
    minos 11.0
      sdk 26.2
"""
    assert HATCH_BUILD._parse_macos_min_version(output) == (11, 0)


def test_mac_platform_tag_uses_binary_min_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the macOS wheel tag from the bundled binary metadata."""
    monkeypatch.setattr(HATCH_BUILD, "_macos_arch", lambda _path: "x86_64")
    monkeypatch.setattr(HATCH_BUILD, "_macos_min_version", lambda _path: (10, 12))

    tag = HATCH_BUILD._mac_platform_tag(Path("dummy"))

    assert tag == "py3-none-macosx_10_12_x86_64"
