"""Tests for CLI configuration and flow helpers."""

from __future__ import annotations

import os
import datetime as dt
from pathlib import Path

import pytest

from imexp.cli import main as cli


def make_three_dirs(base: Path) -> tuple[Path, Path, Path]:
    """Create three sibling directories for ordering tests."""
    first = base / "first"
    second = base / "second"
    third = base / "third"
    first.mkdir()
    second.mkdir()
    third.mkdir()
    return first, second, third


def input_sequence(values: list[str]):
    """Build an input replacement that yields provided values."""
    iterator = iter(values)

    def _input(_prompt: str = "") -> str:
        return next(iterator)

    return _input


def test_resolve_platform_and_db_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Selecting macOS skips backup selection."""
    monkeypatch.setattr("builtins.input", input_sequence(["macOS"]))
    platform, db_path = cli.resolve_platform_and_db(None, None, True)
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


def test_resolve_user_labels() -> None:
    """User label prompts are removed from exports."""
    assert True


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
            diagnostics=False,
            no_lazy=False,
            version=False,
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
            diagnostics=False,
            no_lazy=False,
            version=False,
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
    )
    cmd = cli.build_export_command(config_run)
    assert "--platform" in cmd
    assert "iOS" in cmd
    assert "/backup" in cmd


def test_export_parser_rejects_profile_and_filter_together() -> None:
    """Profiles and raw conversation filters are mutually exclusive."""
    parser = cli.build_export_fallback_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--profile", "client-a", "--conversation-filter", "alice"])


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
    cli.postprocess_exports(
        cli.PostprocessContext(
            export_dir=export_dir,
            contacts_map=contacts_map,
            overrides=overrides,
        ),
        ask_for_missing=False,
    )

    renamed_files = list(export_dir.glob("*.txt"))
    assert len(renamed_files) == 1
    assert renamed_files[0].name == "chat_Alice_Bob.txt"
    assert "Alice" in renamed_files[0].read_text()
    assert "Bob" in renamed_files[0].read_text()


def test_build_profile_filename_aliases_uses_contacts_and_names() -> None:
    """Profile aliases combine handle-derived contact names and explicit names."""
    profile = cli.ProfileConfig(
        name="pastor-will",
        handles=("+19049885338", "+19048373582"),
        names=("Will Junior",),
        label="Pastor Will",
        slug="pastor-will",
        platform="",
        format="",
        copy_method="",
        use_caller_id=None,
        output_dir="",
    )

    aliases = cli.build_profile_filename_aliases(
        profile,
        {
            "+19049885338": "Pastor Will Simpson",
            "+19048373582": "Will Junior",
        },
    )

    assert aliases["Pastor Will Simpson"] == "Pastor Will"
    assert aliases["Will Junior"] == "Pastor Will"


def test_apply_filename_aliases_preserves_colliding_files(tmp_path: Path) -> None:
    """Alias normalization does not overwrite distinct conversation files."""
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    first = export_dir / "Pastor Will Simpson.txt"
    second = export_dir / "Will Junior.txt"
    first.write_text("one")
    second.write_text("two")

    cli.apply_filename_aliases(
        export_dir,
        {
            "Pastor Will Simpson": "Pastor Will",
            "Will Junior": "Pastor Will",
        },
    )

    renamed_files = sorted(path.name for path in export_dir.glob("*.txt"))
    assert renamed_files == [
        "Pastor Will [Will Junior].txt",
        "Pastor Will.txt",
    ]


def test_update_history_end() -> None:
    """History stores epoch-millisecond end timestamps."""
    history: dict[str, int] = {}
    end_dt = dt.datetime(2024, 1, 2, 3, 4, 5)
    cli.update_history_end(history, end_dt)
    assert history["last_end_ms"] == cli.datetime_to_epoch_ms(end_dt)


def test_should_run_export_wizard_without_profile() -> None:
    """No-arg export without a profile falls back to the wizard."""
    args = cli.build_export_fallback_parser().parse_args([])
    assert cli.should_run_export_wizard([], args, None) is True


def test_should_run_export_wizard_skips_when_profile_selected() -> None:
    """Auto-loaded profiles bypass the wizard."""
    args = cli.build_export_fallback_parser().parse_args([])
    profile = cli.ProfileConfig(
        name="client-a",
        handles=("+15551234567",),
        names=(),
        label="",
        slug="",
        platform="",
        format="",
        copy_method="",
        use_caller_id=None,
        output_dir="",
    )
    assert cli.should_run_export_wizard([], args, profile) is False


def test_should_run_export_wizard_honors_explicit_flag() -> None:
    """--wizard forces the prompt flow."""
    args = cli.build_export_fallback_parser().parse_args(["--wizard"])
    assert cli.should_run_export_wizard(["--wizard"], args, None) is True


def test_list_recent_exports(tmp_path: Path) -> None:
    """Recent exports are ordered by mtime."""
    first, second, third = make_three_dirs(tmp_path)
    os.utime(first, (1, 1))
    os.utime(second, (2, 2))
    os.utime(third, (3, 3))

    recent = cli.list_recent_exports(tmp_path, limit=2)
    assert len(recent) == 2
    assert recent[0] == third
