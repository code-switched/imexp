"""Hatchling build hook for platform-specific bundled wheels."""

from __future__ import annotations

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


def _platform_tag() -> str:
    """Return the best py3-none platform tag for the current build host."""
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
        build_data["tag"] = _platform_tag()

        force_include = build_data.setdefault("force_include", {})
        force_include[str(bundled_binary)] = f"imexp/bin/{bundled_binary.name}"
