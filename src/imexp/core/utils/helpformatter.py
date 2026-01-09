"""Colored argparse help formatting utilities."""

import argparse
import re
from enum import Enum
from typing import Optional

from imexp.core.utils import ansi


class Color(str, Enum):
    """ANSI color codes."""

    RED = ansi.RED
    GREEN = ansi.GREEN
    YELLOW = ansi.YELLOW
    BLUE = ansi.BLUE
    MAGENTA = ansi.MAGENTA
    CYAN = ansi.CYAN
    GREY = ansi.GREY
    SAGE = ansi.SAGE
    ROSE = ansi.ROSE
    LILAC = ansi.LILAC


def _colorize(text: str, color: Optional[Color]) -> str:
    """Return text wrapped in ANSI colors if provided."""
    if color is None:
        return text
    return f"{color.value}{text}{ansi.RESET}"


class ColourHelpFormatter(argparse.HelpFormatter):
    """HelpFormatter that adds color to key parts of the help output."""

    def start_section(self, heading: str) -> None:  # type: ignore[override]
        colored_heading = _colorize(heading, Color.GREEN)
        super().start_section(colored_heading)

    def add_usage(self, usage, actions, groups, prefix=None):
        if prefix is None:
            prefix = f"{_colorize('usage:', Color.GREEN)} "
        super().add_usage(usage, actions, groups, prefix)

    def _format_action_invocation(self, action: argparse.Action) -> str:
        if not action.option_strings:
            return super()._format_action_invocation(action)

        parts = [_colorize(flag, Color.CYAN) for flag in action.option_strings]

        if action.nargs != 0:
            metavar = self._format_args(action, action.dest.upper())
            parts[-1] = f"{parts[-1]} {metavar}"
        return ", ".join(parts)

    def _format_args(self, action, default_metavar):
        text = super()._format_args(action, default_metavar)
        return _colorize(text, Color.GREY)

    def _get_help_string(self, action: argparse.Action) -> str:  # noqa: N802
        """Return help string with colored default values."""
        help_text = super()._get_help_string(action)
        match = re.search(r"\\(default: ([^)]+)\\)", help_text)
        if match:
            value = match.group(1)
            colored_value = _colorize(value, Color.YELLOW)
            help_text = help_text.replace(match.group(0), f"(default: {colored_value})")
        return help_text
