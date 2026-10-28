"""Object storage adapter for original regulation files (MinIO / S3 compatible).

A local filesystem fallback is provided so the whole stack remains runnable in
environments without MinIO (e.g. local dev / CI). Selection is automatic: if the
MinIO client cannot be initialised the adapter transparently switches to local
storage under ``./storage``.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.core.config import get_settings

_SETTINGS = get_settings()


class ObjectStore:
    """Store / fetch original regulation documents."""

    def __init__(self) -> None:
        self.backend = "minio"
        self._client = None
        self._local_root = Path("./storage")
        try:  # pragma: no cover - depends on environment
            import certifi
            from minio import Minio
            from urllib3 import PoolManager
            from urllib3.util import Retry, Timeout

            self._client = Minio(
                _SETTINGS.MINIO_ENDPOINT,
                access_key=_SETTINGS.MINIO_ACCESS_KEY,
                secret_key=_SETTINGS.MINIO_SECRET_KEY,
                secure=_SETTINGS.MINIO_SECURE,
                http_client=PoolManager(
                    timeout=Timeout(connect=2, read=5, total=7),
                    maxsize=10,
                    cert_reqs="CERT_REQUIRED",
                    ca_certs=os.environ.get("SSL_CERT_FILE") or certifi.where(),
                    retries=Retry(
                        total=1, connect=1, read=1, redirect=0, status=1,
                        backoff_factor=0,
                        status_forcelist=[500, 502, 503, 504],
                        respect_retry_after_header=False,
                    ),
                ),
            )
            if not self._client.bucket_exists(_SETTINGS.MINIO_BUCKET):
                self._client.make_bucket(_SETTINGS.MINIO_BUCKET)
        except Exception:  # noqa: BLE001
            self.backend = "local"
            self._local_root.mkdir(exist_ok=True)

    def put_object(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        if self.backend == "minio" and self._client is not None:
            from io import BytesIO

            self._client.put_object(
                _SETTINGS.MINIO_BUCKET,
                key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return f"minio://{_SETTINGS.MINIO_BUCKET}/{key}"
        path = self._local_root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"local://{path}"

    @staticmethod
    def _object_name(key: str) -> str:
        """Normalise legacy URI-shaped keys to the backend object name.

        The database historically stores ``minio://bucket/key`` and local URI
        values.  Recovery must read those records without logging either the
        source path or object contents.
        """
        if key.startswith("minio://"):
            _, _, remainder = key.partition("://")
            _, _, name = remainder.partition("/")
            return name
        if key.startswith("local://"):
            return os.path.basename(key.removeprefix("local://"))
        return os.path.basename(key)

    def get_object(self, key: str) -> bytes | None:
        object_name = self._object_name(key)
        # The URI scheme records where this particular object was written.
        # A later MinIO connection must not make legacy local:// originals
        # unreadable (or send their names to a different backend).
        if key.startswith("local://") or self.backend == "local":
            path = self._local_root / object_name
            return path.read_bytes() if path.exists() else None
        try:
            resp = self._client.get_object(_SETTINGS.MINIO_BUCKET, object_name)  # type: ignore[union-attr]
            try:
                return resp.read()
            finally:
                # Streaming responses do not release their connection on read.
                # Return it even when the read fails so later downloads can run.
                try:
                    resp.close()
                finally:
                    resp.release_conn()
        except Exception:  # noqa: BLE001
            return None

    def delete_object(self, key: str) -> bool:
        """Delete an object. Returns True if deleted, False if not found / failed."""
        object_name = self._object_name(key)
        if key.startswith("local://") or self.backend == "local":
            path = self._local_root / object_name
            if path.exists():
                path.unlink()
                return True
            return False
        try:
            self._client.remove_object(_SETTINGS.MINIO_BUCKET, object_name)  # type: ignore[union-attr]
            return True
        except Exception:  # noqa: BLE001
            return False

    def presign(self, key: str) -> str:
        object_name = self._object_name(key)
        if self.backend == "minio" and self._client is not None:
            try:
                return self._client.presigned_get_object(_SETTINGS.MINIO_BUCKET, object_name)
            except Exception:  # noqa: BLE001
                return ""
        return f"/api/v1/regulations/file/{object_name}"


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = ObjectStore()
    return _store
