"""Tests for relabel CLI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from imexp.cli import main as cli


def test_relabel_contacts_only_skips_prompts() -> None:
    """Contacts-only relabel skips prompts for missing names."""
    args = cli.argparse.Namespace(contacts_only=True)
    assert args.contacts_only is True


def test_resolve_relabel_paths_requires_export_path(tmp_path: Path) -> None:
    """Non-interactive relabel requires explicit export path."""
    args = cli.argparse.Namespace(export_path=None)
    with pytest.raises(ValueError):
        cli.resolve_relabel_paths(tmp_path, args, interactive=False)


def test_select_export_path_numeric_choice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting recent export by index returns expected path."""
    paths = {name: tmp_path / name for name in ("first", "second", "third")}
    for path in paths.values():
        path.mkdir()
    first = paths["first"]
    second = paths["second"]
    third = paths["third"]

    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    selected = cli.select_export_path(tmp_path)
    assert selected in {first, second, third}


def test_resolve_platform_requires_db_path_for_ios() -> None:
    """Non-interactive iOS requires db path."""
    with pytest.raises(ValueError):
        cli.resolve_platform_and_db("iOS", None, False)


def test_postprocess_exports_recursive(tmp_path: Path) -> None:
    """Relabeling is recursive in nested directories."""
    export_dir = tmp_path / "exports"
    nested_dir = export_dir / "nested"
    nested_dir.mkdir(parents=True)
    file_path = nested_dir / "chat_+14155551212.txt"
    file_path.write_text("Hi +14155551212")

    cli.postprocess_exports(
        cli.PostprocessContext(
            export_dir=export_dir,
            contacts_map={"+14155551212": "Alice"},
            overrides={},
        ),
        ask_for_missing=False,
    )

    renamed_files = list(nested_dir.glob("*.txt"))
    assert renamed_files[0].name == "chat_Alice.txt"
    assert "Alice" in renamed_files[0].read_text()
