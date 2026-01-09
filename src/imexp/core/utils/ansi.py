"""ANSI color escape codes with backward-compatible lowercase access."""

from typing import Final

_CODES: Final[dict[str, str]] = {
    'RED': '\033[31m',
    'GREEN': '\033[32m',
    'YELLOW': '\033[33m',
    'BLUE': '\033[34m',
    'MAGENTA': '\033[35m',
    'CYAN': '\033[36m',
    'GREY': '\033[90m',
    'SAGE': '\033[38;5;108m',
    'ROSE': '\033[38;5;167m',
    'LILAC': '\033[38;5;141m',
    'RESET': '\033[0m',
}

globals().update(_CODES)
_ALIASES: Final[dict[str, str]] = {name.lower(): name for name in _CODES}

__all__ = sorted(list[str](_ALIASES.keys()) + list[str](_CODES.keys()))


def __getattr__(name: str) -> str:
    alias = _ALIASES.get(name)
    if alias is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    return globals()[alias]


def __dir__() -> list[str]:
    return sorted(list[str](globals().keys()) + list[str](_ALIASES.keys()))
