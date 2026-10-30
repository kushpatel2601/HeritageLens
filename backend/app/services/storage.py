from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_\-.]{0,199}$")


def validate_key(key: str) -> str:
    if not _KEY_RE.match(key) or ".." in key or key.startswith("/"):
        raise ValueError(f"invalid storage key: {key!r}")
    return key


class Storage(Protocol):
    """Blob storage. Keys are opaque, content-addressed where possible, never user-controlled paths."""

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...
    def local_path(self, key: str) -> Path | None: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / validate_key(key)).resolve()
        if self.root not in p.parents:
            raise ValueError("key escapes storage root")
        return p

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic on POSIX & NTFS

        await asyncio.to_thread(_write)
        return key

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path | None:
        return self._path(key)


class S3Storage:
    """S3 / MinIO / R2 backend. boto3 is sync, so calls are pushed to a thread."""

    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=validate_key(key), Body=data, ContentType=content_type
        )
        return key

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=validate_key(key))
        body: bytes = await asyncio.to_thread(obj["Body"].read)
        return body

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=self.bucket, Key=validate_key(key))
            return True
        except Exception:
            return False

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=validate_key(key))

    def local_path(self, key: str) -> Path | None:
        return None


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.storage_dir)
