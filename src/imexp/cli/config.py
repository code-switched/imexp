"""Configuration loading and management."""

import os
import logging
import configparser
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger("imexp")

IOS_BACKUP_ROOT = Path("~/Library/Application Support/MobileSync/Backup").expanduser()
CONFIG_FILE = "imexp/config.ini"


@dataclass(frozen=True)
class ExportDefaults:
    """User-configurable export defaults from config.ini."""

    platform: str
    format: str
    copy_method: str
    start_date: str
    conversation_filter: str
    default_profile: str
    use_caller_id: bool
    output_dir: str


@dataclass(frozen=True)
class ProfileConfig:
    """Saved client/project export profile."""

    name: str
    handles: tuple[str, ...]
    names: tuple[str, ...]
    label: str
    slug: str
    platform: str
    format: str
    copy_method: str
    use_caller_id: bool | None
    output_dir: str


@dataclass(frozen=True)
class CLIConfig:
    """Resolved CLI configuration."""

    export: ExportDefaults
    profiles: dict[str, ProfileConfig]
    path: Path
    root_dir: Path


def _find_repo_root(start: Path) -> Path:
    """Find a repo root from the provided starting path."""
    current = start.resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
        if (parent / ".git").exists():
            return parent
    return current


def _get_project_root() -> Path:
    """Find project root from the current working directory."""
    return _find_repo_root(Path.cwd())


def _get_data_dir(root_dir: Path | None = None) -> Path:
    """Get the data directory."""
    env_value = os.getenv("IMEXP_DATA_DIR")
    if env_value:
        return Path(env_value).expanduser()

    resolved_root = root_dir or _get_project_root()
    return resolved_root / "data"


def _get_config_dir(root_dir: Path | None = None) -> Path:
    """Get the config directory."""
    env_value = os.getenv("IMEXP_CONFIG_DIR")
    if env_value:
        return Path(env_value).expanduser()
    return _get_data_dir(root_dir=root_dir) / "config"


def _resolve_config_path(config_path: Path | None = None) -> Path:
    """Resolve the config file path."""
    if config_path is not None:
        return config_path.expanduser().resolve()

    env_path = os.getenv("IMEXP_CONFIG_FILE")
    if env_path:
        return Path(env_path).expanduser().resolve()

    root_dir = _get_project_root()
    return _get_config_dir(root_dir=root_dir) / CONFIG_FILE


def _resolve_root_dir(config_path: Path | None, resolved_path: Path) -> Path:
    """Resolve the owning repo root for the active config."""
    if config_path is None and not os.getenv("IMEXP_CONFIG_FILE"):
        return _get_project_root()

    return _find_repo_root(resolved_path)


def _ensure_config_file(path: Path) -> None:
    """Create the config file with defaults if it doesn't exist."""
    if path.exists():
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_default_config_template(), encoding="utf-8")


def _get_value(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
) -> str | None:
    """Read a string value from the config parser."""
    if not parser.has_section(section):
        return None

    if not parser.has_option(section, key):
        return None

    value = parser.get(section, key).strip()
    if not value:
        return None

    return value


def _get_bool_value(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
) -> bool | None:
    """Read a boolean value from the config parser."""
    if not parser.has_section(section):
        return None

    if not parser.has_option(section, key):
        return None

    raw_value = parser.get(section, key).strip()
    if not raw_value:
        return None

    return parser.getboolean(section, key)


def _get_list_value(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
) -> tuple[str, ...]:
    """Read a newline or comma-separated list value from the config parser."""
    raw_value = _get_value(parser, section, key)
    if raw_value is None:
        return ()

    values: list[str] = []
    for line in raw_value.splitlines():
        for token in line.split(","):
            stripped = token.strip()
            if not stripped:
                continue
            if stripped in values:
                continue
            values.append(stripped)
    return tuple(values)


def _load_profiles(parser: configparser.ConfigParser) -> dict[str, ProfileConfig]:
    """Load saved export profiles from the config parser."""
    profiles: dict[str, ProfileConfig] = {}
    for section in parser.sections():
        if not section.startswith("profile."):
            continue

        name = section.partition(".")[2].strip()
        if not name:
            continue

        profiles[name] = ProfileConfig(
            name=name,
            handles=_get_list_value(parser, section, "handles"),
            names=_get_list_value(parser, section, "names"),
            label=_get_value(parser, section, "label") or "",
            slug=_get_value(parser, section, "slug") or "",
            platform=_get_value(parser, section, "platform") or "",
            format=_get_value(parser, section, "format") or "",
            copy_method=_get_value(parser, section, "copy_method") or "",
            use_caller_id=_get_bool_value(parser, section, "use_caller_id"),
            output_dir=_get_value(parser, section, "output_dir") or "",
        )
    return profiles


def load_config(config_path: Path | None = None) -> CLIConfig:
    """Load configuration from the config.ini file."""
    parser = configparser.ConfigParser()
    resolved_path = _resolve_config_path(config_path)
    root_dir = _resolve_root_dir(config_path, resolved_path)
    _ensure_config_file(resolved_path)
    parser.read(resolved_path)

    output_dir = _get_value(parser, "export", "output_dir") or ""
    output_dir = os.environ.get("IMEXP_BASE_OUTPUT_DIR", output_dir) or "./data/messages/sms"

    return CLIConfig(
        export=ExportDefaults(
            platform=_get_value(parser, "export", "platform") or "",
            format=_get_value(parser, "export", "format") or "txt",
            copy_method=_get_value(parser, "export", "copy_method") or "full",
            start_date=_get_value(parser, "export", "start_date") or "",
            conversation_filter=_get_value(parser, "export", "conversation_filter") or "",
            default_profile=_get_value(parser, "export", "default_profile") or "",
            use_caller_id=_get_bool_value(parser, "export", "use_caller_id") or False,
            output_dir=output_dir,
        ),
        profiles=_load_profiles(parser),
        path=resolved_path,
        root_dir=root_dir,
    )


def base_output_dir(
    cli_config: CLIConfig | None = None,
    profile: ProfileConfig | None = None,
) -> Path:
    """Return the base output directory for exports."""
    if profile and profile.output_dir:
        profile_path = Path(profile.output_dir)
        if profile_path.is_absolute():
            return profile_path
        if cli_config:
            return cli_config.root_dir / profile_path
        return profile_path
    if cli_config:
        output_path = Path(cli_config.export.output_dir)
        if output_path.is_absolute():
            return output_path
        return cli_config.root_dir / output_path
    value = os.environ.get("IMEXP_BASE_OUTPUT_DIR", "./data/messages/sms")
    output_path = Path(value)
    if output_path.is_absolute():
        return output_path
    return _get_project_root() / output_path


def _default_config_template() -> str:
    return """# imexp CLI configuration
# This file is auto-generated on first run.
# Values here serve as defaults; CLI flags always override.

[export]
# Source platform (macOS or iOS). Leave empty to prompt interactively.
platform =

# Output format for exported messages.
# Options: txt, html
format = txt

# Attachment copy method.
# Options: disabled, clone, basic, full
copy_method = full

# Default start date for new exports and snapshots.
# Leave empty to start from the CLI value, export metadata, history, or now.
start_date =

# Default conversation filter (comma-separated).
# This is the filter passed to imessage-exporter --conversation-filter.
# Leave empty to export all conversations.
conversation_filter =

# Default saved profile for `imexp` and `imexp export` when no selector is passed.
default_profile =

# Use caller ID instead of "Me" in exports.
use_caller_id = true

# Base output directory for exports.
# Can also be set via IMEXP_BASE_OUTPUT_DIR environment variable.
output_dir = ./data/messages/sms

# Example saved profile:
#
# [profile.client-name]
# handles =
#     +15551234567
#     client@example.com
# names =
#     Client Contact
#     Alternate Contact Label
# label = Client Contact
# slug = client-contact
# platform = macOS
# format = txt
# copy_method = full
# use_caller_id = true
# output_dir = ./data/messages/sms
"""
