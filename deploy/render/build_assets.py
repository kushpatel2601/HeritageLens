"""Package the archive snapshot and the lean text model as release assets for the Render image.

Run from the repository root with the backend virtualenv (it needs the `ml` and `export` extras):

    backend\\.venv\\Scripts\\python deploy\\render\\build_assets.py --upload

What it does:
  1. data:  a consistent SQLite snapshot (sqlite3 backup API, safe while the local API is running) plus
            the object storage, as heritagelens-data-<sha>.tar.gz (unpacked into backend/var);
  2. model: `app.cli export-lean-model`, verified against fastembed on the archive's own text, as
            lean-minilm-<sha>.tar.gz (unpacked into backend/var/models/lean-minilm);
  3. --upload: attaches both to the `deploy-assets` GitHub release (created on first use) with `gh`;
  4. records each URL + SHA-256 in deploy/render/assets.lock.json, which fetch_assets.py verifies at
     image build time. Commit the lock file to redeploy with the new assets.

`--only data` or `--only model` rebuilds one asset and keeps the other lock entry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "backend"
VAR = BACKEND / "var"
LOCK = HERE / "assets.lock.json"
TAG = "deploy-assets"
DEST = {"data": "backend/var", "model": "backend/var/models/lean-minilm"}
STEM = {"data": "heritagelens-data", "model": "lean-minilm"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_data(db: Path, out: Path) -> None:
    out.mkdir(parents=True)
    src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(out / "heritagelens.db")
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")
        dst.execute("VACUUM")
    finally:
        src.close()
        dst.close()
    shutil.copytree(VAR / "storage", out / "storage", ignore=shutil.ignore_patterns("*.tmp", "*.part", ".tmp*"))


def export_model(lean_dir: Path | None, out: Path, archive_texts: int) -> None:
    if lean_dir is not None:
        shutil.copytree(lean_dir, out)
        return
    cmd = [sys.executable, "-m", "app.cli", "export-lean-model", "--out", str(out)]
    if archive_texts:
        cmd += ["--archive-texts", str(archive_texts)]
    subprocess.run(cmd, cwd=BACKEND, check=True)


def pack(folder: Path, stem: str, out_dir: Path) -> Path:
    tmp = out_dir / f"{stem}.tar.gz"
    with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(folder).as_posix())
    final = out_dir / f"{stem}-{sha256(tmp)[:12]}.tar.gz"
    tmp.replace(final)
    return final


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def upload(files: list[Path]) -> str:
    repo = gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").stdout.strip()
    if not repo:
        sys.exit("could not resolve the GitHub repository; is gh authenticated?")
    if gh("release", "view", TAG).returncode != 0:
        created = gh(
            "release", "create", TAG, "--title", "Deploy assets", "--latest=false",
            "--notes", "Archive snapshot and lean text model baked into the Render image (deploy/render).",
        )  # fmt: skip
        if created.returncode != 0:
            sys.exit(created.stderr)
    done = gh("release", "upload", TAG, *map(str, files), "--clobber")
    if done.returncode != 0:
        sys.exit(done.stderr)
    return repo


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=sorted(DEST), help="rebuild one asset, keep the other lock entry")
    parser.add_argument("--db", type=Path, default=VAR / "heritagelens.db")
    parser.add_argument("--lean-dir", type=Path, help="reuse an existing export-lean-model output")
    parser.add_argument("--archive-texts", type=int, default=500, help="archive chunks in the export parity check")
    parser.add_argument("--out", type=Path, default=VAR / "deploy", help="where the tarballs are written")
    parser.add_argument("--upload", action="store_true", help="attach to the GitHub release and update the lock")
    args = parser.parse_args()

    kinds = [args.only] if args.only else ["data", "model"]
    if "data" in kinds and not args.db.is_file():
        sys.exit(f"database not found: {args.db}")
    args.out.mkdir(parents=True, exist_ok=True)

    built: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="hl-assets-") as tmp:
        for kind in kinds:
            stage = Path(tmp) / kind
            if kind == "data":
                snapshot_data(args.db, stage)
            else:
                export_model(args.lean_dir, stage, args.archive_texts)
            built[kind] = pack(stage, STEM[kind], args.out)
            print(f"{kind}: {built[kind].name} ({built[kind].stat().st_size / 1e6:.1f} MB)")

    if not args.upload:
        print(f"built in {args.out}; re-run with --upload to publish and update {LOCK.name}")
        return
    repo = upload(list(built.values()))
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.is_file() else {"assets": {}}
    for kind, path in built.items():
        lock["assets"][kind] = {
            "url": f"https://github.com/{repo}/releases/download/{TAG}/{path.name}",
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "dest": DEST[kind],
        }
    LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"uploaded to {repo}@{TAG}; updated {LOCK.relative_to(ROOT)} - commit it to redeploy")


if __name__ == "__main__":
    main()
