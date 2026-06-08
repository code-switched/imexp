"""Tests for CLI help formatting and fallback parsing."""

from __future__ import annotations

import argparse

from imexp.cli import main as cli
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


def test_export_fallback_parser_defaults() -> None:
    """Fallback export parser provides expected defaults."""
    parser = cli.build_export_fallback_parser()
    args = parser.parse_args([])
    assert args.command == "export"
    assert args.profile is None
    assert args.wizard is False
    assert args.verbose is False
