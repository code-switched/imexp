"""Tests for bundled exporter binary resolution."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from imexp.core import exporter_binary


def test_bundled_binary_name_windows() -> None:
    """Windows wheels should look for an .exe payload."""
    assert exporter_binary.bundled_binary_name("win32") == "imessage-exporter.exe"


def test_bundled_binary_name_posix() -> None:
    """POSIX wheels should look for the bare executable name."""
    assert exporter_binary.bundled_binary_name("darwin") == "imessage-exporter"


def test_resolve_exporter_binary_prefers_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit environment override takes precedence."""
    binary = tmp_path / "custom-exporter"
    binary.write_text("binary")
    monkeypatch.setenv(exporter_binary.EXPORTER_PATH_ENV, str(binary))
    monkeypatch.setattr(exporter_binary.shutil, "which", lambda _name: None)

    resolved = exporter_binary.resolve_exporter_binary(binary_dir=tmp_path / "missing")

    assert resolved == binary


def test_resolve_exporter_binary_uses_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bundled binaries are used before PATH lookup."""
    binary = tmp_path / exporter_binary.bundled_binary_name()
    binary.write_text("binary")
    binary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    monkeypatch.delenv(exporter_binary.EXPORTER_PATH_ENV, raising=False)
    monkeypatch.setattr(exporter_binary.shutil, "which", lambda _name: None)

    resolved = exporter_binary.resolve_exporter_binary(binary_dir=tmp_path)

    assert resolved == binary
    if os.name != "nt":
        assert binary.stat().st_mode & stat.S_IXUSR


def test_resolve_exporter_binary_falls_back_to_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PATH lookup still works for source installs and development."""
    path_binary = tmp_path / "imessage-exporter"
    path_binary.write_text("binary")
    monkeypatch.delenv(exporter_binary.EXPORTER_PATH_ENV, raising=False)
    monkeypatch.setattr(
        exporter_binary.shutil,
        "which",
        lambda _name: str(path_binary),
    )

    resolved = exporter_binary.resolve_exporter_binary(binary_dir=tmp_path / "missing")

    assert resolved == path_binary


def test_resolve_exporter_binary_missing_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing env, bundle, and PATH should raise a clear error."""
    monkeypatch.delenv(exporter_binary.EXPORTER_PATH_ENV, raising=False)
    monkeypatch.setattr(exporter_binary.shutil, "which", lambda _name: None)

    with pytest.raises(FileNotFoundError, match="imessage-exporter is not available"):
        exporter_binary.resolve_exporter_binary(binary_dir=tmp_path / "missing")
