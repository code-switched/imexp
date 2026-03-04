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
        "format = html\n"
        "copy_method = basic\n"
        "conversation_filter = alice,bob\n"
        "use_caller_id = false\n"
        "output_dir = /tmp/exports\n"
    )
    cfg = config.load_config(config_path=ini_path)
    assert cfg.export.platform == "macOS"
    assert cfg.export.format == "html"
    assert cfg.export.copy_method == "basic"
    assert cfg.export.conversation_filter == "alice,bob"
    assert cfg.export.use_caller_id is False
    assert cfg.export.output_dir == "/tmp/exports"


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
    assert defaults.use_caller_id == "enabled"


def test_resolve_help_defaults_fallback() -> None:
    """Without config, help defaults use hardcoded values."""
    defaults = cli.resolve_help_defaults(None)
    assert defaults.platform == "prompt"
    assert defaults.format == "txt"
    assert defaults.conversation_filter == "none"


def test_apply_config_defaults_fills_missing(tmp_path: Path) -> None:
    """Config defaults fill in args that weren't set on CLI."""
    ini_path = tmp_path / "config.ini"
    ini_path.write_text(
        "[export]\n"
        "platform = macOS\n"
        "conversation_filter = lee\n"
        "use_caller_id = true\n"
    )
    cfg = config.load_config(config_path=ini_path)

    args = argparse.Namespace(
        platform=None,
        conversation_filter=None,
        use_caller_id=False,
        format="txt",
        copy_method="full",
    )
    cli.apply_config_defaults(args, cfg)

    assert args.platform == "macOS"
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
    )
    cli.apply_config_defaults(args, cfg)

    assert args.platform == "iOS"
    assert args.conversation_filter == "cli-filter"


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
