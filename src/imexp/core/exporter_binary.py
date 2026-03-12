"""Resolution helpers for the bundled imessage-exporter binary."""

from __future__ import annotations

import os
import shutil
import stat
import sys
from pathlib import Path


EXPORTER_PATH_ENV = "IMEXP_EXPORTER_PATH"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = PACKAGE_ROOT / "bin"


def bundled_binary_name(platform_name: str | None = None) -> str:
    """Return the packaged binary name for the current platform."""
    current_platform = platform_name or sys.platform
    if current_platform.startswith("win"):
        return "imessage-exporter.exe"
    return "imessage-exporter"


def _ensure_executable(path: Path) -> Path:
    """Set executable bits on bundled binaries when needed."""
    if os.name == "nt":
        return path

    mode = path.stat().st_mode
    if mode & stat.S_IXUSR:
        return path

    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def bundled_binary_path(binary_dir: Path | None = None) -> Path | None:
    """Return the bundled binary path if a wheel packaged one."""
    root = binary_dir or BUNDLE_DIR
    path = root / bundled_binary_name()
    if not path.is_file():
        return None
    return _ensure_executable(path)


def _resolve_env_override() -> Path | None:
    """Return an explicit binary path override from the environment."""
    env_value = os.getenv(EXPORTER_PATH_ENV)
    if not env_value:
        return None

    path = Path(env_value).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"{EXPORTER_PATH_ENV} points to a missing file: {path}"
        )
    if path.is_dir():
        raise IsADirectoryError(
            f"{EXPORTER_PATH_ENV} must point to a file, not a directory: {path}"
        )
    return _ensure_executable(path)


def resolve_exporter_binary(binary_dir: Path | None = None) -> Path:
    """Resolve the exporter binary from env override, bundle, or PATH."""
    override = _resolve_env_override()
    if override:
        return override

    bundled = bundled_binary_path(binary_dir=binary_dir)
    if bundled:
        return bundled

    on_path = shutil.which("imessage-exporter")
    if on_path:
        return Path(on_path)

    raise FileNotFoundError(
        "imessage-exporter is not available. Install an official imexp wheel "
        f"for {sys.platform}, set {EXPORTER_PATH_ENV}, or add imessage-exporter "
        "to PATH."
    )
