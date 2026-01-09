"""Configuration helpers for the CLI."""

from __future__ import annotations

import os
from pathlib import Path


IOS_BACKUP_ROOT = Path("~/Library/Application Support/MobileSync/Backup").expanduser()


def base_output_dir() -> Path:
    """Return the base output directory for exports."""
    value = os.environ.get("IMEXP_BASE_OUTPUT_DIR", "./data/messages/sms")
    return Path(value)
