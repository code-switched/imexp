"""Setuptools hooks for platform-specific wheel tagging."""

from __future__ import annotations

from pathlib import Path
from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel as _bdist_wheel

from packaging import tags


BUNDLE_DIR = Path(__file__).resolve().parent / "src" / "imexp" / "bin"


def _has_bundled_binary() -> bool:
    """Return True when a platform binary has been staged into the package."""
    if not BUNDLE_DIR.exists():
        return False
    return any(BUNDLE_DIR.glob("imessage-exporter*"))


class bdist_wheel(_bdist_wheel):
    """Emit platform wheels only when a bundled binary is present."""

    def finalize_options(self) -> None:
        super().finalize_options()
        if _has_bundled_binary():
            self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        tag = super().get_tag()
        if not _has_bundled_binary():
            return tag

        _, _, platform_tag = tag
        bundled_tag = ("py3", "none", platform_tag)
        supported = {
            (item.interpreter, item.abi, item.platform) for item in tags.sys_tags()
        }
        if bundled_tag not in supported:
            raise ValueError(f"unsupported wheel tag {bundled_tag}")
        return bundled_tag


setup(cmdclass={"bdist_wheel": bdist_wheel})
