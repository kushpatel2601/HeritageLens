"""Download, verify and unpack the assets pinned in assets.lock.json (stdlib only; runs in `docker build`).

Usage (from the repository root, or WORKDIR in the image):  python deploy/render/fetch_assets.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

LOCK = Path(__file__).resolve().with_name("assets.lock.json")
ATTEMPTS = 4


def download(url: str, target: Path) -> str:
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "heritagelens-deploy"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as fh:
        for block in iter(lambda: response.read(1 << 20), b""):
            digest.update(block)
            fh.write(block)
    return digest.hexdigest()


def fetch(name: str, spec: dict[str, str], root: Path) -> None:
    dest = root / spec["dest"]
    with tempfile.TemporaryDirectory(prefix="hl-fetch-") as tmp:
        archive = Path(tmp) / "asset.tar.gz"
        for attempt in range(1, ATTEMPTS + 1):
            try:
                got = download(spec["url"], archive)
                break
            except OSError as exc:
                if attempt == ATTEMPTS:
                    sys.exit(f"{name}: download failed: {exc}")
                print(f"{name}: {exc}; retrying", flush=True)
                time.sleep(5 * attempt)
        if got != spec["sha256"]:
            sys.exit(f"{name}: checksum mismatch (expected {spec['sha256']}, got {got})")
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            tar.extractall(dest, filter="data")
    print(f"{name}: {spec['url'].rsplit('/', 1)[-1]} -> {spec['dest']} ({int(spec['bytes']) / 1e6:.1f} MB, sha256 ok)")


def main() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    root = Path.cwd()
    for name, spec in lock["assets"].items():
        fetch(name, spec, root)


if __name__ == "__main__":
    main()
