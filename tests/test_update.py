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
    meta = {"conv_filter": "test", "last_end_ms": 1717243200000}
    cli.save_export_meta(tmp_path, meta)
    loaded = cli.load_export_meta(tmp_path)
    assert loaded["conv_filter"] == "test"
    assert loaded["last_end_ms"] == 1717243200000


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
    assert meta["profile"] == ""
    assert meta["platform"] == "macOS"
    assert meta["last_end_ms"] == cli.datetime_to_epoch_ms(dt.datetime(2024, 6, 1, 12, 0, 0))
    assert "updated_at_ms" in meta


def test_merge_text_files_append(tmp_path: Path) -> None:
    """New transcript blocks are merged into an existing conversation file."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    (target / "chat.txt").write_text("line 1\nline 2\n")
    (staging / "chat.txt").write_text("line 3\nline 4\n")

    cli.merge_text_files(staging, target)

    merged = (target / "chat.txt").read_text()
    assert merged == "line 1\nline 2\n\nline 3\nline 4\n"


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


def test_resolve_update_target_no_path_returns_none(tmp_path: Path) -> None:
    """No export path and no existing exports returns None for bootstrap."""

    class Args:
        export_path = None
        conversation_filter = None

    result = cli.resolve_update_target(tmp_path, Args(), interactive=False)
    assert result is None


def test_resolve_update_dates_from_meta(tmp_path: Path) -> None:
    """Update dates are resolved from export_meta.json."""
    cli.save_export_meta(
        tmp_path,
        {"last_end_ms": cli.datetime_to_epoch_ms(dt.datetime(2024, 6, 15, 10, 0, 0))},
    )

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

    history = {"last_end_ms": cli.datetime_to_epoch_ms(dt.datetime(2024, 3, 10, 8, 0, 0))}
    dates = cli.resolve_update_dates(Args(), tmp_path, history)
    assert cli.date_to_cli(dates.start) == "2024-03-10"


def test_resolve_update_dates_explicit_override(tmp_path: Path) -> None:
    """CLI --start-date takes precedence over meta and history."""
    cli.save_export_meta(
        tmp_path,
        {"last_end_ms": cli.datetime_to_epoch_ms(dt.datetime(2024, 6, 15, 10, 0, 0))},
    )

    class Args:
        start_date = "2024-01-01"
        end_date = None

    dates = cli.resolve_update_dates(Args(), tmp_path, {})
    assert cli.date_to_cli(dates.start) == "2024-01-01"


def test_collect_inputs_cli_uses_config_start_date(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Config default start date seeds snapshot-style non-interactive exports."""
    monkeypatch.setattr(
        cli,
        "resolve_platform_and_db",
        lambda _platform, _db_path, _interactive: ("macOS", ""),
    )
    monkeypatch.setattr(
        cli,
        "resolve_conversation_filter_strict",
        lambda conv_filter, _platform, _db_path: conv_filter,
    )
    args = cli.build_export_fallback_parser().parse_args([])
    args.config_start_date = "2024-02-03"

    config_run = cli.collect_inputs_cli(
        args=args,
        export_base=tmp_path,
        history_path=tmp_path / "history.json",
        contacts_path=tmp_path / "contacts.json",
    )

    assert cli.date_to_cli(config_run.dates.start) == "2024-02-03"


def test_run_continuous_ignores_config_start_date_when_meta_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Incremental updates keep using export metadata over config defaults."""
    export_base = tmp_path / "exports"
    target_dir = export_base / "client-a"
    contacts_path = export_base / "contacts.json"
    history_path = export_base / "history.json"
    export_base.mkdir()
    target_dir.mkdir()
    cli.save_export_meta(
        target_dir,
        {"last_end_ms": cli.datetime_to_epoch_ms(dt.datetime(2024, 6, 15, 10, 0, 0))},
    )

    captured: dict[str, cli.RunConfig] = {}

    def fake_run_update_export(
        config_run: cli.RunConfig,
        _target_dir: Path,
        _export_base: Path,
        _contacts_path: Path,
        selected_profile=None,
    ) -> None:
        captured["config_run"] = config_run

    monkeypatch.setattr(
        cli,
        "resolve_platform_and_db",
        lambda _platform, _db_path, _interactive: ("macOS", ""),
    )
    monkeypatch.setattr(
        cli,
        "resolve_conversation_filter_strict",
        lambda conv_filter, _platform, _db_path: conv_filter,
    )
    monkeypatch.setattr(cli, "run_update_export", fake_run_update_export)

    args = cli.build_export_fallback_parser().parse_args([])
    args.config_start_date = "2024-01-01"

    cli.run_continuous(
        args=args,
        export_base=export_base,
        contacts_path=contacts_path,
        history_path=history_path,
        history={},
        interactive=False,
    )

    assert cli.date_to_cli(captured["config_run"].dates.start) == "2024-06-15"


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


def test_find_update_target_empty(tmp_path: Path) -> None:
    """No export dirs returns None."""
    assert cli.find_update_target(tmp_path, "") is None


def test_find_update_target_single_dir(tmp_path: Path) -> None:
    """Single export dir is returned regardless of filter."""
    export = tmp_path / "2024-01-01-00-00-00"
    export.mkdir()
    assert cli.find_update_target(tmp_path, "anything") == export


def test_find_update_target_matches_by_filter(tmp_path: Path) -> None:
    """When multiple dirs exist, matches by conv_filter in export_meta."""
    dir_a = tmp_path / "export-a"
    dir_b = tmp_path / "export-b"
    dir_a.mkdir()
    dir_b.mkdir()

    cli.save_export_meta(dir_a, {"conv_filter": "alice"})
    cli.save_export_meta(dir_b, {"conv_filter": "bob"})

    assert cli.find_update_target(tmp_path, "bob") == dir_b
    assert cli.find_update_target(tmp_path, "alice") == dir_a


def test_find_update_target_prefers_profile_match(tmp_path: Path) -> None:
    """Profiles take precedence over raw filter matching."""
    dir_a = tmp_path / "export-a"
    dir_b = tmp_path / "export-b"
    dir_a.mkdir()
    dir_b.mkdir()

    cli.save_export_meta(dir_a, {"conv_filter": "alice", "profile": "client-a"})
    cli.save_export_meta(dir_b, {"conv_filter": "alice", "profile": "client-b"})

    assert cli.find_update_target(tmp_path, "alice", profile_name="client-b") == dir_b


def test_find_update_target_no_match(tmp_path: Path) -> None:
    """Multiple dirs with no matching filter returns None."""
    dir_a = tmp_path / "export-a"
    dir_b = tmp_path / "export-b"
    dir_a.mkdir()
    dir_b.mkdir()

    cli.save_export_meta(dir_a, {"conv_filter": "alice"})
    cli.save_export_meta(dir_b, {"conv_filter": "bob"})

    assert cli.find_update_target(tmp_path, "charlie") is None


def test_resolve_update_target_auto_detects(tmp_path: Path) -> None:
    """Auto-detects when there is exactly one export dir."""
    export = tmp_path / "only-export"
    export.mkdir()

    class Args:
        export_path = None
        conversation_filter = None

    result = cli.resolve_update_target(tmp_path, Args(), interactive=False)
    assert result == export


def test_default_export_dir_from_filter(tmp_path: Path) -> None:
    """Folder name is derived from conversation filter."""
    result = cli.default_export_dir(tmp_path, "alice,bob")
    assert result == tmp_path / "alice-bob"


def test_default_export_dir_from_profile(tmp_path: Path) -> None:
    """Profile names become the default export folder label."""
    profile = cli.ProfileConfig(
        name="client-a",
        handles=("+15551234567",),
        names=("Client A",),
        label="Client A",
        slug="client-a-export",
        platform="",
        format="",
        copy_method="",
        use_caller_id=None,
        output_dir="",
    )
    result = cli.default_export_dir(tmp_path, "", profile=profile)
    assert result == tmp_path / "client-a-export"


def test_default_export_dir_no_filter(tmp_path: Path) -> None:
    """Falls back to timestamp when no filter provided."""
    result = cli.default_export_dir(tmp_path, "")
    assert result.parent == tmp_path
    assert result.name != ""


def test_bootstrap_export_dir_creates_folder(tmp_path: Path) -> None:
    """Bootstrap creates the directory derived from conv filter."""
    result = cli.bootstrap_export_dir(tmp_path, "lee,phlo")
    assert result == tmp_path / "lee-phlo"
    assert result.exists()


def test_bootstrap_export_dir_uses_profile_name(tmp_path: Path) -> None:
    """Bootstrap uses the profile name when one is selected."""
    profile = cli.ProfileConfig(
        name="client-a",
        handles=("+15551234567",),
        names=(),
        label="Client A",
        slug="",
        platform="",
        format="",
        copy_method="",
        use_caller_id=None,
        output_dir="",
    )
    result = cli.bootstrap_export_dir(tmp_path, "", profile=profile)
    assert result == tmp_path / "Client-A"
    assert result.exists()


def test_merge_text_files_no_trailing_newline(tmp_path: Path) -> None:
    """Merging a file without trailing newline still produces valid spacing."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    (target / "chat.txt").write_text("line 1")
    (staging / "chat.txt").write_text("line 2\n")

    cli.merge_text_files(staging, target)

    merged = (target / "chat.txt").read_text()
    assert merged == "line 1\n\nline 2\n"


def test_merge_text_files_dedupes_overlapping_transcript_blocks(tmp_path: Path) -> None:
    """Overlapping transcript windows do not duplicate prior messages."""
    staging = tmp_path / "staging"
    target = tmp_path / "target"
    staging.mkdir()
    target.mkdir()

    existing = (
        "Mar 24, 2026  3:57:42 PM\n"
        "Phlo Young\n"
        "Following up\n\n"
        "Mar 24, 2026  4:00:34 PM\n"
        "Lia McBride\n"
        "Sorry Phlo! I will add time! Back in the Uk now!!\n"
    )
    staged = (
        "Mar 20, 2026  5:10:22 PM\n"
        "Shawn swyx Wang\n"
        "hey Lia\n\n"
        "Mar 24, 2026  3:57:42 PM\n"
        "Phlo Young\n"
        "Following up\n\n"
        "Mar 24, 2026  4:00:34 PM\n"
        "Lia McBride\n"
        "Sorry Phlo! I will add time! Back in the Uk now!!\n"
    )
    (target / "chat.txt").write_text(existing)
    (staging / "chat.txt").write_text(staged)

    cli.merge_text_files(staging, target)

    merged = (target / "chat.txt").read_text()
    assert merged.count("Mar 24, 2026  3:57:42 PM") == 1
    assert merged.count("Mar 24, 2026  4:00:34 PM") == 1
    assert merged.index("Mar 20, 2026  5:10:22 PM") < merged.index("Mar 24, 2026  3:57:42 PM")


def test_merge_transcript_text_sorts_backfilled_blocks_chronologically() -> None:
    """Backfilled staged messages are inserted by timestamp instead of appended."""
    existing = (
        "Apr 09, 2026  2:48:04 AM\n"
        "Shawn swyx Wang\n"
        "lots of space onthe left side of keynotes\n"
    )
    staged = (
        "Apr 08, 2026  2:31:30 AM\n"
        "Raouf\n"
        "Wow what a line to get in.\n\n"
        "Apr 09, 2026  2:48:04 AM\n"
        "Shawn swyx Wang\n"
        "lots of space onthe left side of keynotes\n\n"
        "Apr 09, 2026  2:48:15 AM\n"
        "Shawn swyx Wang\n"
        "bring if can\n"
    )

    merged = cli.merge_transcript_text(existing, staged)

    assert merged.index("Apr 08, 2026  2:31:30 AM") < merged.index("Apr 09, 2026  2:48:04 AM")
    assert merged.index("Apr 09, 2026  2:48:04 AM") < merged.index("Apr 09, 2026  2:48:15 AM")
    assert merged.count("Apr 09, 2026  2:48:04 AM") == 1


def test_run_update_export_cleans_staging_on_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Successful updates remove the run staging directory and empty staging root."""
    export_base = tmp_path / "exports"
    target_dir = export_base / "client-a"
    contacts_path = export_base / "contacts.json"
    history_path = export_base / "history.json"
    export_base.mkdir()

    def fake_run_exporter(config_run: cli.RunConfig) -> None:
        config_run.paths.export_path.mkdir(parents=True, exist_ok=True)
        (config_run.paths.export_path / "chat.txt").write_text("hello\n")

    monkeypatch.setattr(cli, "run_exporter", fake_run_exporter)
    monkeypatch.setattr(cli, "load_contacts_for_platform", lambda _platform, _db_path: {})
    monkeypatch.setattr(
        cli,
        "postprocess_exports",
        lambda _context, ask_for_missing=False: None,
    )

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
            profile_name="client-a",
        ),
        dates=cli.DateRange(start=dt.datetime(2024, 1, 1), end=dt.datetime(2024, 1, 2)),
        paths=cli.PathsConfig(
            export_path=target_dir,
            contacts_json=contacts_path,
            history_json=history_path,
        ),
    )

    cli.run_update_export(config_run, target_dir, export_base, contacts_path)

    assert not (export_base / cli.STAGING_DIR).exists()
    assert (target_dir / "chat.txt").exists()


def test_run_update_export_preserves_failed_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failed updates leave the populated staging directory on disk."""
    export_base = tmp_path / "exports"
    target_dir = export_base / "client-a"
    contacts_path = export_base / "contacts.json"
    history_path = export_base / "history.json"
    export_base.mkdir()

    def fake_run_exporter(config_run: cli.RunConfig) -> None:
        config_run.paths.export_path.mkdir(parents=True, exist_ok=True)
        (config_run.paths.export_path / "chat.txt").write_text("hello\n")

    def fail_postprocess(_context: cli.PostprocessContext, ask_for_missing: bool = False) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(cli, "run_exporter", fake_run_exporter)
    monkeypatch.setattr(cli, "load_contacts_for_platform", lambda _platform, _db_path: {})
    monkeypatch.setattr(cli, "postprocess_exports", fail_postprocess)

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
            profile_name="client-a",
        ),
        dates=cli.DateRange(start=dt.datetime(2024, 1, 1), end=dt.datetime(2024, 1, 2)),
        paths=cli.PathsConfig(
            export_path=target_dir,
            contacts_json=contacts_path,
            history_json=history_path,
        ),
    )

    with pytest.raises(ValueError, match="boom"):
        cli.run_update_export(config_run, target_dir, export_base, contacts_path)

    staging_root = export_base / cli.STAGING_DIR
    staging_children = list(staging_root.iterdir())
    assert len(staging_children) == 1
    assert (staging_children[0] / "chat.txt").exists()
    assert "Preserved staged files at" in capsys.readouterr().err
