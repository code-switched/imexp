"""Tests for config.ini loading and CLI default application."""

from __future__ import annotations

import argparse
from pathlib import Path

from imexp.cli import config
from imexp.cli import main as cli


def test_load_config_creates_default(tmp_path: Path) -> None:
    """First load creates a config.ini with defaults."""
    ini_path = tmp_path / "config.ini"
    cfg = config.load_config(config_path=ini_path)
    assert ini_path.exists()
    assert cfg.export.format == "txt"
    assert cfg.export.copy_method == "full"
    assert cfg.export.use_caller_id is True


def test_load_config_reads_values(tmp_path: Path) -> None:
    """Config values are read from the ini file."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "platform = macOS\n"
        "start_date = 2024-01-01\n"
        "format = html\n"
        "copy_method = basic\n"
        "conversation_filter = alice,bob\n"
        "default_profile = client-a\n"
        "use_caller_id = false\n"
        "output_dir = /tmp/exports\n"
        "\n"
        "[profile.client-a]\n"
        "handles =\n"
        "    +15551234567\n"
        "    client@example.com\n"
        "names =\n"
        "    Client Contact\n"
        "label = Client Contact\n"
        "slug = client-contact\n"
        "copy_method = clone\n"
    )
    cfg = config.load_config(config_path=ini_path)
    assert cfg.export.platform == "macOS"
    assert cfg.export.start_date == "2024-01-01"
    assert cfg.export.format == "html"
    assert cfg.export.copy_method == "basic"
    assert cfg.export.conversation_filter == "alice,bob"
    assert cfg.export.default_profile == "client-a"
    assert cfg.export.use_caller_id is False
    assert cfg.export.output_dir == "/tmp/exports"
    assert cfg.profiles["client-a"].handles == ("+15551234567", "client@example.com")
    assert cfg.profiles["client-a"].names == ("Client Contact",)
    assert cfg.profiles["client-a"].label == "Client Contact"
    assert cfg.profiles["client-a"].slug == "client-contact"
    assert cfg.profiles["client-a"].copy_method == "clone"


def test_load_config_empty_values_use_defaults(tmp_path: Path) -> None:
    """Empty ini values fall back to hardcoded defaults."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text("[export]\nplatform =\nformat =\n")
    cfg = config.load_config(config_path=ini_path)
    assert cfg.export.platform == ""
    assert cfg.export.format == "txt"


def test_load_config_missing_section(tmp_path: Path) -> None:
    """Missing section uses all defaults."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text("# empty config\n")
    cfg = config.load_config(config_path=ini_path)
    assert cfg.export.format == "txt"
    assert cfg.export.conversation_filter == ""


def test_base_output_dir_from_config(tmp_path: Path) -> None:
    """base_output_dir reads from CLIConfig."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text("[export]\noutput_dir = /custom/path\n")
    cfg = config.load_config(config_path=ini_path)
    result = config.base_output_dir(cfg)
    assert result == Path("/custom/path")


def test_resolve_help_defaults_from_config(tmp_path: Path) -> None:
    """Help defaults reflect config values."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "platform = macOS\n"
        "conversation_filter = lee,phlo\n"
        "use_caller_id = true\n"
    )
    cfg = config.load_config(config_path=ini_path)
    defaults = cli.resolve_help_defaults(cfg)
    assert defaults.platform == "macOS"
    assert defaults.conversation_filter == "lee,phlo"
    assert defaults.profile == "none"
    assert defaults.use_caller_id == "enabled"


def test_resolve_help_defaults_fallback() -> None:
    """Without config, help defaults use hardcoded values."""
    defaults = cli.resolve_help_defaults(None)
    assert defaults.platform == "prompt"
    assert defaults.format == "txt"
    assert defaults.conversation_filter == "none"
    assert defaults.profile == "none"


def test_apply_config_defaults_fills_missing(tmp_path: Path) -> None:
    """Config defaults fill in args that weren't set on CLI."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "platform = macOS\n"
        "start_date = 2024-01-01\n"
        "conversation_filter = lee\n"
        "use_caller_id = true\n"
    )
    cfg = config.load_config(config_path=ini_path)

    args = argparse.Namespace(
        platform=None,
        start_date=None,
        conversation_filter=None,
        use_caller_id=False,
        format="txt",
        copy_method="full",
        profile=None,
        wizard=False,
    )
    profile = cli.apply_config_defaults(args, cfg, set())

    assert profile is None
    assert args.platform == "macOS"
    assert args.start_date is None
    assert args.config_start_date == "2024-01-01"
    assert args.conversation_filter == "lee"
    assert args.use_caller_id is True


def test_apply_config_defaults_cli_overrides(tmp_path: Path) -> None:
    """CLI args take precedence over config defaults."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "platform = macOS\n"
        "conversation_filter = default-filter\n"
    )
    cfg = config.load_config(config_path=ini_path)

    args = argparse.Namespace(
        platform="iOS",
        conversation_filter="cli-filter",
        use_caller_id=False,
        format="txt",
        copy_method="full",
        profile=None,
        wizard=False,
    )
    profile = cli.apply_config_defaults(
        args,
        cfg,
        {"platform", "conversation_filter"},
    )

    assert profile is None
    assert args.platform == "iOS"
    assert args.conversation_filter == "cli-filter"


def test_apply_config_defaults_selects_default_profile(tmp_path: Path) -> None:
    """Default profile drives the no-selector export path."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "default_profile = client-a\n"
        "\n"
        "[profile.client-a]\n"
        "handles =\n"
        "    +15551234567\n"
        "    client@example.com\n"
        "names =\n"
        "    Client Contact\n"
        "label = Client Contact\n"
        "slug = client-contact\n"
        "platform = iOS\n"
        "copy_method = basic\n"
        "format = html\n"
        "use_caller_id = true\n"
        "output_dir = /tmp/client-a\n"
    )
    cfg = config.load_config(config_path=ini_path)
    args = argparse.Namespace(
        platform=None,
        conversation_filter=None,
        use_caller_id=False,
        format="txt",
        copy_method="full",
        profile=None,
        wizard=False,
    )

    profile = cli.apply_config_defaults(args, cfg, set())

    assert profile == cfg.profiles["client-a"]
    assert args.profile == "client-a"
    assert args.platform == "iOS"
    assert args.copy_method == "basic"
    assert args.format == "html"
    assert args.use_caller_id is True
    assert args.conversation_filter == "+15551234567,client@example.com"
    assert config.base_output_dir(cfg, profile=profile) == Path("/tmp/client-a")
    assert cli.profile_display_label(profile) == "Client Contact"
    assert cli.profile_folder_name(profile) == "client-contact"


def test_apply_config_defaults_explicit_profile_overrides_default(tmp_path: Path) -> None:
    """Explicit --profile beats the config default profile."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "default_profile = client-a\n"
        "\n"
        "[profile.client-a]\n"
        "handles =\n"
        "    +15551234567\n"
        "\n"
        "[profile.client-b]\n"
        "handles =\n"
        "    +15557654321\n"
    )
    cfg = config.load_config(config_path=ini_path)
    args = argparse.Namespace(
        platform=None,
        conversation_filter=None,
        use_caller_id=False,
        format="txt",
        copy_method="full",
        profile="client-b",
        wizard=False,
    )

    profile = cli.apply_config_defaults(args, cfg, {"profile"})

    assert profile == cfg.profiles["client-b"]
    assert args.profile == "client-b"
    assert args.conversation_filter == "+15557654321"


def test_apply_config_defaults_wizard_skips_default_profile(tmp_path: Path) -> None:
    """--wizard keeps the interactive path instead of auto-loading the default profile."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "default_profile = client-a\n"
        "\n"
        "[profile.client-a]\n"
        "handles =\n"
        "    +15551234567\n"
    )
    cfg = config.load_config(config_path=ini_path)
    args = argparse.Namespace(
        platform=None,
        conversation_filter=None,
        use_caller_id=False,
        format="txt",
        copy_method="full",
        profile=None,
        wizard=True,
    )

    profile = cli.apply_config_defaults(args, cfg, {"wizard"})

    assert profile is None
    assert args.profile is None
    assert args.conversation_filter is None


def test_with_default() -> None:
    """_with_default appends default value to help text."""
    result = cli._with_default("Output format", "txt")
    assert result == "Output format (default: txt)"


def test_help_text_shows_config_defaults(tmp_path: Path) -> None:
    """Help text reflects config.ini defaults."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "conversation_filter = alice,bob\n"
        "format = html\n"
    )
    cfg = config.load_config(config_path=ini_path)
    defaults = cli.resolve_help_defaults(cfg)

    parser = argparse.ArgumentParser()
    cli.add_export_args(parser, help_defaults=defaults)
    help_text = parser.format_help()
    assert "alice,bob" in help_text
    assert "html" in help_text


def test_help_text_shows_profile_default(tmp_path: Path) -> None:
    """Help text reflects the configured default profile."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text("[export]\ndefault_profile = client-a\n")
    cfg = config.load_config(config_path=ini_path)
    defaults = cli.resolve_help_defaults(cfg)

    parser = argparse.ArgumentParser()
    cli.add_export_args(parser, help_defaults=defaults)
    help_text = parser.format_help()
    assert "client-a" in help_text
