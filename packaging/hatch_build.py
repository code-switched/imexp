"""Hatchling build hook for platform-specific bundled wheels."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging import tags


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "src" / "imexp" / "bin"


def _bundled_binary() -> Path | None:
    """Return the staged exporter binary when present."""
    if not BUNDLE_DIR.exists():
        return None

    for path in sorted(BUNDLE_DIR.glob("imessage-exporter*")):
        if path.is_file():
            return path
    return None


def _parse_macos_arch(output: str) -> str:
    """Parse a single macOS architecture from `lipo -archs` output."""
    archs = output.strip().split()
    if len(archs) != 1:
        raise ValueError(f"expected a single macOS architecture, got {archs!r}")

    arch = archs[0]
    if arch not in {"arm64", "x86_64"}:
        raise ValueError(f"unsupported macOS architecture {arch!r}")
    return arch


def _parse_macos_min_version(output: str) -> tuple[int, int]:
    """Parse the minimum macOS version from `vtool -show-build` output."""
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("minos "):
            continue
        version = stripped.split()[1]
        major, minor, *_ = version.split(".")
        return int(major), int(minor)

    in_legacy_version_block = False
    for line in output.splitlines():
        stripped = line.strip()
        if stripped == "cmd LC_VERSION_MIN_MACOSX":
            in_legacy_version_block = True
            continue

        if not in_legacy_version_block:
            continue

        if not stripped.startswith("version "):
            continue

        version = stripped.split()[1]
        major, minor, *_ = version.split(".")
        return int(major), int(minor)

    raise ValueError("could not determine the minimum macOS version for binary")


def _macos_arch(binary: Path) -> str:
    """Return the binary architecture for a staged macOS executable."""
    result = subprocess.run(
        ["lipo", "-archs", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _parse_macos_arch(result.stdout)


def _macos_min_version(binary: Path) -> tuple[int, int]:
    """Return the minimum macOS version for a staged macOS executable."""
    result = subprocess.run(
        ["vtool", "-show-build", str(binary)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _parse_macos_min_version(result.stdout)


def _mac_platform_tag(binary: Path) -> str:
    """Return the best macOS wheel tag for the staged binary."""
    arch = _macos_arch(binary)
    version = _macos_min_version(binary)
    platform_tag = next(tags.mac_platforms(version, arch))
    return f"py3-none-{platform_tag}"


def _platform_tag(binary: Path) -> str:
    """Return the best py3-none platform tag for the staged binary."""
    if sys.platform == "darwin":
        return _mac_platform_tag(binary)

    for tag in tags.sys_tags():
        if tag.interpreter != "py3":
            continue
        if tag.abi != "none":
            continue
        return str(tag)

    raise RuntimeError("could not determine a py3-none platform tag")


class CustomBuildHook(BuildHookInterface):
    """Adjust wheel build data when a platform binary is staged."""

    def initialize(self, version: str, build_data: dict) -> None:
        del version

        bundled_binary = _bundled_binary()
        if bundled_binary is None:
            return

        build_data["pure_python"] = False
        build_data["tag"] = _platform_tag(bundled_binary)

        force_include = build_data.setdefault("force_include", {})
        force_include[str(bundled_binary)] = f"imexp/bin/{bundled_binary.name}"
