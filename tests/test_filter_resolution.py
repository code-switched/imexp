"""Tests for strict conversation filter resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from imexp.cli import main as cli


@pytest.fixture
def contact_records() -> list[cli.ContactRecord]:
    """Return a small contact fixture set."""
    return [
        cli.ContactRecord(name="Bill Jones", handles=("+15551234567",)),
        cli.ContactRecord(name="Bill Jones", handles=("+15557654321",)),
        cli.ContactRecord(name="Alice Smith", handles=("alice@example.com",)),
    ]


def patch_resolution_sources(
    monkeypatch: pytest.MonkeyPatch,
    handles: tuple[str, ...],
    contacts: list[cli.ContactRecord],
) -> None:
    """Patch contact and handle sources for deterministic resolution tests."""
    monkeypatch.setattr(cli, "load_message_handles", lambda _platform, _db_path: handles)
    monkeypatch.setattr(
        cli,
        "load_contact_records_for_platform",
        lambda _platform, _db_path: contacts,
    )


def test_strict_filter_rewrites_exact_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exact handle input rewrites to the canonical exporter handle."""
    patch_resolution_sources(
        monkeypatch,
        handles=("+15551234567",),
        contacts=[],
    )

    resolved = cli.resolve_conversation_filter_strict("(555) 123-4567", "macOS", None)
    assert resolved == "+15551234567"


def test_strict_filter_resolves_exact_case_insensitive_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full exact name resolves to the contact's known message handle."""
    patch_resolution_sources(
        monkeypatch,
        handles=("alice@example.com",),
        contacts=[cli.ContactRecord(name="Alice Smith", handles=("alice@example.com",))],
    )

    resolved = cli.resolve_conversation_filter_strict("alice smith", "macOS", None)
    assert resolved == "alice@example.com"


def test_strict_filter_rejects_partial_name(
    monkeypatch: pytest.MonkeyPatch,
    contact_records: list[cli.ContactRecord],
) -> None:
    """Partial names do not fall through to upstream substring matching."""
    patch_resolution_sources(
        monkeypatch,
        handles=("+15551234567", "+15557654321", "alice@example.com"),
        contacts=contact_records,
    )

    with pytest.raises(ValueError, match="does not exactly match any known handle or contact"):
        cli.resolve_conversation_filter_strict("bill", "macOS", None)


def test_strict_filter_rejects_ambiguous_exact_name(
    monkeypatch: pytest.MonkeyPatch,
    contact_records: list[cli.ContactRecord],
) -> None:
    """Ambiguous exact names fail with candidate handles."""
    patch_resolution_sources(
        monkeypatch,
        handles=("+15551234567", "+15557654321", "alice@example.com"),
        contacts=contact_records,
    )

    with pytest.raises(ValueError, match="matches multiple contacts"):
        cli.resolve_conversation_filter_strict("Bill Jones", "macOS", None)


def test_strict_filter_rejects_unknown_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown exact handles fail instead of broadening the export."""
    patch_resolution_sources(
        monkeypatch,
        handles=("+15551234567",),
        contacts=[],
    )

    with pytest.raises(ValueError, match="does not exactly match any known handle or contact"):
        cli.resolve_conversation_filter_strict("+15550000000", "macOS", None)


def test_no_match_continuous_export_creates_no_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Filter resolution failures stop before any export directory is created."""
    export_base = tmp_path / "exports"
    contacts_path = export_base / "contacts.json"
    history_path = export_base / "history.json"
    export_base.mkdir()

    args = cli.build_export_fallback_parser().parse_args(
        ["--conversation-filter", "bill", "--start-date", "2024-01-01"]
    )

    monkeypatch.setattr(
        cli,
        "resolve_platform_and_db",
        lambda _platform, _db_path, _interactive: ("macOS", ""),
    )
    patch_resolution_sources(
        monkeypatch,
        handles=("+15551234567",),
        contacts=[cli.ContactRecord(name="Bill Jones", handles=("+15551234567",))],
    )

    with pytest.raises(ValueError, match="does not exactly match any known handle or contact"):
        cli.run_continuous(
            args=args,
            export_base=export_base,
            contacts_path=contacts_path,
            history_path=history_path,
            history={},
            interactive=False,
        )

    assert list(export_base.iterdir()) == []
    assert not contacts_path.exists()
    assert not history_path.exists()
