"""Tests for relabel CLI behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from imexp.cli import main as cli


def build_profile(name: str, output_dir: str = "") -> cli.ProfileConfig:
    """Build a profile used by relabel profile-resolution tests."""
    return cli.ProfileConfig(
        name=name,
        handles=("+14155551212",),
        names=("Archive Label",),
        label="Chris Smith",
        slug=name,
        platform="macOS",
        format="txt",
        copy_method="full",
        use_caller_id=True,
        output_dir=output_dir,
        self_label="Chris Smith",
        self_aliases=("💙 Christopher Smith 🧑🏾‍💻",),
    )


def build_cli_config(
    tmp_path: Path,
    profiles: dict[str, cli.ProfileConfig],
    default_profile: str = "",
    output_dir: Path | None = None,
) -> cli.CLIConfig:
    """Build a CLI configuration used by relabel tests."""
    return cli.CLIConfig(
        export=cli.config.ExportDefaults(
            platform="macOS",
            format="txt",
            copy_method="full",
            start_date="",
            conversation_filter="",
            default_profile=default_profile,
            use_caller_id=True,
            output_dir=str(output_dir or tmp_path / "exports"),
        ),
        profiles=profiles,
        path=tmp_path / "config.ini",
        root_dir=tmp_path,
    )


def test_relabel_contacts_only_skips_prompts() -> None:
    """Contacts-only relabel skips prompts for missing names."""
    args = cli.argparse.Namespace(contacts_only=True)
    assert args.contacts_only is True


def test_relabel_parser_accepts_profile() -> None:
    """Relabel accepts an explicit saved profile."""
    parser = cli.build_root_parser()

    args = parser.parse_args(["relabel", "--profile", "crc-team"])

    assert args.profile == "crc-team"


@pytest.mark.parametrize(
    ("explicit_profile", "recorded_profile", "default_profile", "expected_profile"),
    [
        ("explicit", "recorded", "default", "explicit"),
        (None, "recorded", "default", "recorded"),
        (None, "", "default", "default"),
        (None, "", "", None),
    ],
)
def test_resolve_relabel_profile_uses_expected_precedence(
    tmp_path: Path,
    explicit_profile: str | None,
    recorded_profile: str,
    default_profile: str,
    expected_profile: str | None,
) -> None:
    """Relabel prefers explicit, recorded, then default profiles."""
    export_dir = tmp_path / "archive"
    export_dir.mkdir()
    if recorded_profile:
        cli.save_export_meta(export_dir, {"profile": recorded_profile})

    profiles = {
        name: build_profile(name)
        for name in ("explicit", "recorded", "default")
    }
    cli_config = build_cli_config(tmp_path, profiles, default_profile=default_profile)
    args = cli.argparse.Namespace(profile=explicit_profile)

    selected = cli.resolve_relabel_profile(args, cli_config, export_dir)

    assert (selected.name if selected else None) == expected_profile


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


def test_run_relabel_applies_profile_text_and_filename_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relabel applies explicit profile aliases without corrupting ordinary words."""
    export_base = tmp_path / "exports"
    export_dir = export_base / "archive"
    export_dir.mkdir(parents=True)
    file_path = export_dir / "chat_Archive Label.txt"
    file_path.write_text("Merrita Media Meeting 💙 Christopher Smith 🧑🏾‍💻\n")
    profile = build_profile("crc-team")
    cli_config = build_cli_config(tmp_path, {profile.name: profile})
    args = cli.argparse.Namespace(
        export_path=str(export_dir),
        platform="macOS",
        db_path=None,
        contacts_json=None,
        contacts_only=True,
        profile="crc-team",
    )
    monkeypatch.setattr(cli, "load_contacts_for_platform", lambda _platform, _db_path: {})

    cli.run_relabel(export_base, args, interactive=False, cli_config=cli_config)

    renamed_file = export_dir / "chat_Chris Smith.txt"
    assert renamed_file.read_text() == "Merrita Media Meeting Chris Smith\n"


def test_run_relabel_without_profile_preserves_contacts_only_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relabel continues to apply contact mappings when no profile is available."""
    export_base = tmp_path / "exports"
    export_dir = export_base / "archive"
    export_dir.mkdir(parents=True)
    file_path = export_dir / "chat_+14155551212.txt"
    file_path.write_text("Hi +14155551212\n")
    cli_config = build_cli_config(tmp_path, {})
    args = cli.argparse.Namespace(
        export_path=str(export_dir),
        platform="macOS",
        db_path=None,
        contacts_json=None,
        contacts_only=True,
        profile=None,
    )
    monkeypatch.setattr(
        cli,
        "load_contacts_for_platform",
        lambda _platform, _db_path: {"+14155551212": "Alice"},
    )

    cli.run_relabel(export_base, args, interactive=False, cli_config=cli_config)

    renamed_file = export_dir / "chat_Alice.txt"
    assert renamed_file.read_text() == "Hi Alice\n"


def test_run_relabel_uses_selected_profile_contacts_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relabel loads overrides from the selected profile's output directory."""
    global_export_base = tmp_path / "global-exports"
    profile_export_base = tmp_path / "profile-exports"
    export_dir = profile_export_base / "archive"
    export_dir.mkdir(parents=True)
    file_path = export_dir / "chat_+14155551212.txt"
    file_path.write_text("Hi +14155551212\n")
    cli.save_contacts_json(
        profile_export_base / "contacts.json",
        {"overrides": {"+14155551212": "Alice"}},
    )
    profile = build_profile("crc-team", output_dir=str(profile_export_base))
    cli_config = build_cli_config(
        tmp_path,
        {profile.name: profile},
        output_dir=global_export_base,
    )
    args = cli.argparse.Namespace(
        export_path=str(export_dir),
        platform="macOS",
        db_path=None,
        contacts_json=None,
        contacts_only=True,
        profile="crc-team",
    )
    monkeypatch.setattr(cli, "load_contacts_for_platform", lambda _platform, _db_path: {})

    cli.run_relabel(global_export_base, args, interactive=False, cli_config=cli_config)

    renamed_file = export_dir / "chat_Alice.txt"
    assert renamed_file.read_text() == "Hi Alice\n"
