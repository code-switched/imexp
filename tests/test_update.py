"""Tests for update (continuous export) mode."""

import datetime as dt
from pathlib import Path

import pytest

from imexp.cli import main as cli


def test_load_export_meta_missing(tmp_path: Path) -> None:
    """Missing export_meta.json returns empty dict."""
    assert cli.load_export_meta(tmp_path) == {}


def test_load_export_meta_empty(tmp_path: Path) -> None:
    """Empty export_meta.json returns empty dict."""
    (tmp_path / cli.EXPORT_META_FILE).write_text("")
    assert cli.load_export_meta(tmp_path) == {}


def test_save_and_load_export_meta(tmp_path: Path) -> None:
    """Round-trip save/load of export metadata."""
    meta = {"conv_filter": "test", "last_end": "2024-06-01 12:00:00"}
    cli.save_export_meta(tmp_path, meta)
    loaded = cli.load_export_meta(tmp_path)
    assert loaded["conv_filter"] == "test"
    assert loaded["last_end"] == "2024-06-01 12:00:00"


def test_build_export_meta() -> None:
    """Build metadata from a RunConfig."""
    config_run = cli.RunConfig(
        options=cli.ExportOptions(
            platform="macOS",
            db_path="",
            conv_filter="alice",
            use_caller_id=True,
            copy_method="full",
            output_format="txt",
            diagnostics=False,
            no_lazy=False,
            version=False,
        ),
        dates=cli.DateRange(
            start=dt.datetime(2024, 1, 1),
            end=dt.datetime(2024, 6, 1, 12, 0, 0),
        ),
        paths=cli.PathsConfig(
            export_path=Path("/tmp/test"),
            contacts_json=Path("/tmp/contacts.json"),
            history_json=Path("/tmp/history.json"),
        ),
    )
    meta = cli.build_export_meta(config_run)
    assert meta["conv_filter"] == "alice"
    assert meta["platform"] == "macOS"
    assert meta["last_end"] == "2024-06-01 12:00:00"
    assert "updated_at" in meta


def test_merge_text_files_append(tmp_path: Path) -> None:
    """New text is appended to an existing conversation file."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    (target / "chat.txt").write_text("line 1\nline 2\n")
    (staging / "chat.txt").write_text("line 3\nline 4\n")

    cli.merge_text_files(staging, target)

    merged = (target / "chat.txt").read_text()
    assert "line 1" in merged
    assert "line 2" in merged
    assert "line 3" in merged
    assert "line 4" in merged


def test_merge_text_files_new_file(tmp_path: Path) -> None:
    """A new conversation file is copied into the target."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    (staging / "new-chat.txt").write_text("hello world\n")

    cli.merge_text_files(staging, target)

    assert (target / "new-chat.txt").exists()
    assert (target / "new-chat.txt").read_text() == "hello world\n"


def test_merge_text_files_skips_empty(tmp_path: Path) -> None:
    """Empty staged files are not merged."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    (staging / "empty.txt").write_text("   \n")

    cli.merge_text_files(staging, target)

    assert not (target / "empty.txt").exists()


def test_merge_attachments_copies_new(tmp_path: Path) -> None:
    """New attachments are copied to the target."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    staged_att = staging / "attachments" / "172"
    staged_att.mkdir(parents=True)
    (staged_att / "100.png").write_text("image-data")

    copied = cli.merge_attachments(staging, target)

    assert copied == 1
    assert (target / "attachments" / "172" / "100.png").exists()


def test_merge_attachments_skips_existing(tmp_path: Path) -> None:
    """Existing attachments are not overwritten."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    staged_att = staging / "attachments" / "172"
    staged_att.mkdir(parents=True)
    (staged_att / "100.png").write_text("new-data")

    target_att = target / "attachments" / "172"
    target_att.mkdir(parents=True)
    (target_att / "100.png").write_text("old-data")

    copied = cli.merge_attachments(staging, target)

    assert copied == 0
    assert (target_att / "100.png").read_text() == "old-data"


def test_merge_attachments_no_staging_dir(tmp_path: Path) -> None:
    """No attachments dir in staging returns zero."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    copied = cli.merge_attachments(staging, target)
    assert copied == 0


def test_resolve_update_target_explicit(tmp_path: Path) -> None:
    """Explicit --export-path is used as update target."""

    class Args:
        export_path = str(tmp_path)

    result = cli.resolve_update_target(tmp_path, Args(), interactive=False)
    assert result == tmp_path


def test_resolve_update_target_missing_raises() -> None:
    """Missing update target raises FileNotFoundError."""

    class Args:
        export_path = "/nonexistent/path"

    with pytest.raises(FileNotFoundError):
        cli.resolve_update_target(Path("/tmp"), Args(), interactive=False)


def test_resolve_update_target_no_path_non_interactive(tmp_path: Path) -> None:
    """Non-interactive mode without --export-path raises ValueError."""

    class Args:
        export_path = None

    with pytest.raises(ValueError, match="requires --export-path"):
        cli.resolve_update_target(tmp_path, Args(), interactive=False)


def test_resolve_update_dates_from_meta(tmp_path: Path) -> None:
    """Update dates are resolved from export_meta.json."""
    cli.save_export_meta(tmp_path, {"last_end": "2024-06-15 10:00:00"})

    class Args:
        start_date = None
        end_date = None

    dates = cli.resolve_update_dates(Args(), tmp_path, {})
    assert cli.date_to_cli(dates.start) == "2024-06-15"


def test_resolve_update_dates_from_history(tmp_path: Path) -> None:
    """Falls back to history.json when no export_meta.json."""

    class Args:
        start_date = None
        end_date = None

    history = {"last_end": "2024-03-10 08:00:00"}
    dates = cli.resolve_update_dates(Args(), tmp_path, history)
    assert cli.date_to_cli(dates.start) == "2024-03-10"


def test_resolve_update_dates_explicit_override(tmp_path: Path) -> None:
    """CLI --start-date takes precedence over meta and history."""
    cli.save_export_meta(tmp_path, {"last_end": "2024-06-15 10:00:00"})

    class Args:
        start_date = "2024-01-01"
        end_date = None

    dates = cli.resolve_update_dates(Args(), tmp_path, {})
    assert cli.date_to_cli(dates.start) == "2024-01-01"


def test_resolve_update_dates_no_source_raises(tmp_path: Path) -> None:
    """No date source at all raises ValueError."""

    class Args:
        start_date = None
        end_date = None

    with pytest.raises(ValueError, match="Cannot determine start date"):
        cli.resolve_update_dates(Args(), tmp_path, {})


def test_list_recent_exports_excludes_staging(tmp_path: Path) -> None:
    """Staging directory is excluded from recent exports."""
    (tmp_path / cli.STAGING_DIR).mkdir()
    (tmp_path / "real-export").mkdir()

    recent = cli.list_recent_exports(tmp_path)
    names = [p.name for p in recent]
    assert cli.STAGING_DIR not in names
    assert "real-export" in names


def test_merge_text_files_no_trailing_newline(tmp_path: Path) -> None:
    """Appending to a file without trailing newline adds one."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    (target / "chat.txt").write_text("line 1")
    (staging / "chat.txt").write_text("line 2\n")

    cli.merge_text_files(staging, target)

    merged = (target / "chat.txt").read_text()
    assert merged == "line 1\nline 2\n"
