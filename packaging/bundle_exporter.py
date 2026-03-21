"""Download and stage a pinned imessage-exporter release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import stat
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path(__file__).resolve().with_name("imessage-exporter-assets.json")
PACKAGE_BIN_DIR = ROOT / "src" / "imexp" / "bin"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Stage a pinned imessage-exporter binary into src/imexp/bin.",
    )
    parser.add_argument(
        "--target",
        help="Target key from packaging/imessage-exporter-assets.json",
    )
    return parser.parse_args()


def load_manifest() -> dict:
    """Load the pinned upstream asset manifest."""
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def detect_target() -> str:
    """Infer the packaging target from the current runner."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"

    if system == "darwin" and machine in {"x86_64", "amd64"}:
        return "macos-x86_64"

    if system == "windows" and machine in {"x86_64", "amd64"}:
        return "windows-x86_64"

    raise ValueError(f"unsupported build target for {system}/{machine}")


def asset_url(version: str, asset_name: str) -> str:
    """Build the GitHub release download URL for an upstream asset."""
    return (
        "https://github.com/ReagentX/imessage-exporter/releases/download/"
        f"{version}/{asset_name}"
    )


def sha256_digest(path: Path) -> str:
    """Return the SHA256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_bin_dir() -> None:
    """Remove previously staged binaries so each wheel ships one payload."""
    if not PACKAGE_BIN_DIR.exists():
        return

    for path in PACKAGE_BIN_DIR.iterdir():
        if path.is_file():
            path.unlink()


def stage_binary(target: str) -> Path:
    """Download, verify, and stage a single release asset."""
    manifest = load_manifest()
    targets = manifest["targets"]
    if target not in targets:
        raise KeyError(f"unknown target {target!r}")

    entry = targets[target]
    version = manifest["version"]
    url = asset_url(version, entry["asset_name"])

    with tempfile.TemporaryDirectory() as tmpdir:
        download_path = Path(tmpdir) / entry["asset_name"]
        request = urllib.request.Request(url, headers={"User-Agent": "imexp-build"})
        with urllib.request.urlopen(request) as response:
            download_path.write_bytes(response.read())

        digest = sha256_digest(download_path)
        if digest != entry["sha256"]:
            raise ValueError(
                f"checksum mismatch for {entry['asset_name']}: "
                f"expected {entry['sha256']}, got {digest}"
            )

        PACKAGE_BIN_DIR.mkdir(parents=True, exist_ok=True)
        clear_bin_dir()
        staged_path = PACKAGE_BIN_DIR / entry["output_name"]
        shutil.copyfile(download_path, staged_path)

    if staged_path.suffix != ".exe":
        staged_path.chmod(
            stat.S_IRUSR
            | stat.S_IWUSR
            | stat.S_IXUSR
            | stat.S_IRGRP
            | stat.S_IXGRP
            | stat.S_IROTH
            | stat.S_IXOTH
        )

    return staged_path


def main() -> None:
    """Stage the requested or inferred upstream binary."""
    args = parse_args()
    target = args.target or detect_target()
    staged_path = stage_binary(target)
    print(f"Staged {target} binary at {staged_path}")


if __name__ == "__main__":
    main()
