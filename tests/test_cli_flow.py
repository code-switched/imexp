"""Tests for CLI configuration and flow helpers."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from imexp.cli import main as cli


def input_sequence(values: list[str]):
    """Build an input replacement that yields provided values."""
    iterator = iter(values)

    def _input(_prompt: str = "") -> str:
        return next(iterator)

    return _input


def test_resolve_platform_and_db_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting macOS skips backup selection."""
    monkeypatch.setattr("builtins.input", input_sequence(["macOS"]))
    platform, db_path = cli.resolve_platform_and_db()
    assert platform == "macOS"
    assert db_path == ""


def test_resolve_date_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """Date range prompts parse expected inputs."""
    monkeypatch.setattr("builtins.input", input_sequence(["2024-01-02", "2024-02-03"]))
    dates = cli.resolve_date_range(None)
    assert cli.date_to_cli(dates.start) == "2024-01-02"
    assert cli.date_to_cli(dates.end or dt.datetime.min) == "2024-02-03"


def test_resolve_output_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Output path uses sanitized label when provided."""
    monkeypatch.setattr("builtins.input", input_sequence(["My Label"]))
    output = cli.resolve_output_path(tmp_path)
    assert output == tmp_path / "My-Label"


def test_resolve_user_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """User label prompts map inputs into labels."""
    monkeypatch.setattr("builtins.input", input_sequence(["Me", "123, 456"]))
    labels = cli.resolve_user_labels()
    assert labels.me_label == "Me"
    assert labels.my_numbers == ["123", "456"]


def test_build_export_command_macos(tmp_path: Path) -> None:
    """Exporter command includes macOS defaults and filters."""
    config_run = cli.RunConfig(
        options=cli.ExportOptions(
            platform="macOS",
            db_path="",
            conv_filter="test",
            use_caller_id=True,
            copy_method="full",
            output_format="txt",
        ),
        dates=cli.DateRange(
            start=dt.datetime(2024, 1, 1, 0, 0, 0),
            end=dt.datetime(2024, 1, 2, 0, 0, 0),
        ),
        paths=cli.PathsConfig(
            export_path=tmp_path,
            contacts_json=tmp_path / "contacts.json",
            history_json=tmp_path / "history.json",
        ),
        labels=cli.UserLabels(me_label=None, my_numbers=[]),
    )
    cmd = cli.build_export_command(config_run)
    assert cmd[:2] == ["imessage-exporter", "--format"]
    assert "--copy-method" in cmd
    assert "--conversation-filter" in cmd
    assert "--use-caller-id" in cmd
    assert "--end-date" in cmd


def test_build_export_command_ios(tmp_path: Path) -> None:
    """Exporter command uses iOS platform and db path."""
    config_run = cli.RunConfig(
        options=cli.ExportOptions(
            platform="iOS",
            db_path="/backup",
            conv_filter="",
            use_caller_id=False,
            copy_method="full",
            output_format="html",
        ),
        dates=cli.DateRange(
            start=dt.datetime(2024, 1, 1, 0, 0, 0),
            end=None,
        ),
        paths=cli.PathsConfig(
            export_path=tmp_path,
            contacts_json=tmp_path / "contacts.json",
            history_json=tmp_path / "history.json",
        ),
        labels=cli.UserLabels(me_label=None, my_numbers=[]),
    )
    cmd = cli.build_export_command(config_run)
    assert "--platform" in cmd
    assert "iOS" in cmd
    assert "/backup" in cmd


def test_load_contacts_json_empty_file(tmp_path: Path) -> None:
    """Empty contacts file yields default overrides."""
    path = tmp_path / "contacts.json"
    path.write_text("")
    data = cli.load_contacts_json(path)
    assert data == {"overrides": {}}


def test_load_history_empty_file(tmp_path: Path) -> None:
    """Empty history file yields empty history."""
    path = tmp_path / "history.json"
    path.write_text("")
    history = cli.load_history(path)
    assert history == {}


def test_postprocess_exports(tmp_path: Path) -> None:
    """Postprocess replaces tokens in files and filenames."""
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    file_path = export_dir / "chat_+14155551212_test@example.com.txt"
    file_path.write_text("Hi +14155551212 test@example.com")

    contacts_map = {"+14155551212": "Alice"}
    overrides: dict[str, str] = {"test@example.com": "Bob"}
    labels = cli.UserLabels(me_label=None, my_numbers=[])

    cli.postprocess_exports(
        cli.PostprocessContext(
            export_dir=export_dir,
            contacts_map=contacts_map,
            overrides=overrides,
            labels=labels,
        ),
        ask_for_missing=False,
    )

    renamed_files = list(export_dir.glob("*.txt"))
    assert len(renamed_files) == 1
    assert renamed_files[0].name == "chat_Alice_Bob.txt"
    assert "Alice" in renamed_files[0].read_text()
    assert "Bob" in renamed_files[0].read_text()


def test_update_history_end() -> None:
    """History stores ISO-formatted end timestamp."""
    history: dict[str, str] = {}
    end_dt = dt.datetime(2024, 1, 2, 3, 4, 5)
    cli.update_history_end(history, end_dt)
    assert history["last_end"] == "2024-01-02 03:04:05"
