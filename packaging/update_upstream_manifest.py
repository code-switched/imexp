"""Refresh the pinned imessage-exporter asset manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path


MANIFEST_PATH = Path(__file__).resolve().with_name("imessage-exporter-assets.json")
RELEASES_API = "https://api.github.com/repos/ReagentX/imessage-exporter/releases"
TARGETS = {
    "macos-arm64": {
        "asset_name": "imessage-exporter-aarch64-apple-darwin",
        "output_name": "imessage-exporter",
    },
    "macos-x86_64": {
        "asset_name": "imessage-exporter-x86_64-apple-darwin",
        "output_name": "imessage-exporter",
    },
    "windows-x86_64": {
        "asset_name": "imessage-exporter-x86_64-pc-windows-gnu.exe",
        "output_name": "imessage-exporter.exe",
    },
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Refresh the pinned imessage-exporter asset manifest.",
    )
    version_group = parser.add_mutually_exclusive_group(required=True)
    version_group.add_argument("--latest", action="store_true")
    version_group.add_argument("--version", help="Exact upstream release tag to pin")
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the refreshed manifest back to packaging/imessage-exporter-assets.json",
    )
    return parser.parse_args()


def request_json(url: str) -> dict:
    """Fetch JSON from the GitHub API."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "imexp-build",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def sha256_digest(path: Path) -> str:
    """Return the SHA256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_data(version: str | None, latest: bool) -> dict:
    """Resolve a release body from the GitHub API."""
    if latest:
        return request_json(f"{RELEASES_API}/latest")

    if version is None:
        raise ValueError("version must be provided when --latest is not used")
    return request_json(f"{RELEASES_API}/tags/{version}")


def download_checksum(url: str, asset_name: str) -> str:
    """Download an asset to a temp file and return its SHA256 digest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        download_path = Path(tmpdir) / asset_name
        request = urllib.request.Request(url, headers={"User-Agent": "imexp-build"})
        with urllib.request.urlopen(request) as response:
            download_path.write_bytes(response.read())
        return sha256_digest(download_path)


def build_manifest(release: dict) -> dict:
    """Build the pinned manifest for the supported wheel targets."""
    assets = {asset["name"]: asset for asset in release["assets"]}
    manifest = {"version": release["tag_name"], "targets": {}}

    for target, target_data in TARGETS.items():
        asset_name = target_data["asset_name"]
        if asset_name not in assets:
            raise KeyError(f"release {release['tag_name']} is missing asset {asset_name}")

        asset = assets[asset_name]
        manifest["targets"][target] = {
            "asset_name": asset_name,
            "output_name": target_data["output_name"],
            "sha256": download_checksum(asset["browser_download_url"], asset_name),
        }

    return manifest


def main() -> None:
    """Refresh and optionally write the upstream asset manifest."""
    args = parse_args()
    release = release_data(args.version, args.latest)
    manifest = build_manifest(release)
    manifest_text = json.dumps(manifest, indent=2)

    if args.write:
        MANIFEST_PATH.write_text(f"{manifest_text}\n", encoding="utf-8")
        print(f"Updated {MANIFEST_PATH} to {manifest['version']}")
        return

    print(manifest_text)


if __name__ == "__main__":
    main()
