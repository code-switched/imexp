"""Tests for CLI help formatting and fallback parsing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from imexp.cli import main as cli
from imexp.cli.config import CLIConfig, ExportDefaults
from imexp.core.utils.helpformatter import ColourHelpFormatter


def test_subcommand_help_uses_colour_formatter() -> None:
    """Subcommands use the colored formatter."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()
    export_parser = cli.build_export_parser(subparsers)
    relabel_parser = cli.build_relabel_parser(subparsers)
    assert export_parser.formatter_class is ColourHelpFormatter
    assert relabel_parser.formatter_class is ColourHelpFormatter


def test_root_parser_uses_colour_formatter() -> None:
    """Root parser uses the colored formatter."""
    parser = cli.build_root_parser()
    assert parser.formatter_class is ColourHelpFormatter


def test_root_parser_accepts_version_flag() -> None:
    """Root parser accepts a top-level version flag without a subcommand."""
    parser = cli.build_root_parser()
    args = parser.parse_args(["--version"])
    assert args.version is True
    assert args.command is None


def test_export_fallback_parser_defaults() -> None:
    """Fallback export parser provides expected defaults."""
    parser = cli.build_export_fallback_parser()
    args = parser.parse_args([])
    assert args.command == "export"
    assert args.profile is None
    assert args.wizard is False
    assert args.verbose is False


def test_main_prints_root_version(
    monkeypatch,
    capsys,
) -> None:
    """Top-level --version prints the imexp version and exits early."""
    cli_config = CLIConfig(
        export=ExportDefaults(
            platform="",
            format="txt",
            copy_method="full",
            start_date="",
            conversation_filter="",
            default_profile="",
            use_caller_id=True,
            output_dir="./data/messages/sms",
        ),
        profiles={},
        path=Path("/tmp/config.ini"),
    )
    monkeypatch.setattr(cli.config, "load_config", lambda: cli_config)
    monkeypatch.setattr(cli, "get_cli_version", lambda: "0.2.1")
    monkeypatch.setattr(sys, "argv", ["imexp", "--version"])

    assert cli.main() == 0
    assert capsys.readouterr().out.strip() == "0.2.1"
