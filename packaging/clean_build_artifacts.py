"""Remove local build artifacts before packaging."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIRS = [
    ROOT / "build",
    ROOT / "dist",
    ROOT / "src" / "imexp.egg-info",
]
BUNDLE_DIR = ROOT / "src" / "imexp" / "bin"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Remove local build artifacts.")
    parser.add_argument(
        "--include-bundle",
        action="store_true",
        help="Also remove any staged binary from src/imexp/bin.",
    )
    return parser.parse_args()


def remove_path(path: Path) -> None:
    """Delete a directory tree if it exists."""
    if not path.exists():
        return
    shutil.rmtree(path)
    print(f"Removed {path}")


def main() -> None:
    """Delete packaging artifacts that can contaminate later builds."""
    args = parse_args()
    for path in GENERATED_DIRS:
        remove_path(path)

    if args.include_bundle:
        remove_path(BUNDLE_DIR)


if __name__ == "__main__":
    main()
