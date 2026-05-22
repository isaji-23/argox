"""Local filesystem implementation of :class:`StorageBackend`."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping, Optional

from argox_collector.storage.base import (
    BlobData,
    BlobMetadata,
    BlobNotFoundError,
    StorageBackend,
    StorageError,
    StoredBlob,
    normalize_key,
)

_METADATA_SUFFIX = ".meta.json"


class LocalStorageBackend(StorageBackend):
    """Persist blobs as files under a single root directory.

    Each blob ``foo/bar.jsonl`` is stored as two files:

    - ``<root>/foo/bar.jsonl`` — the raw payload.
    - ``<root>/foo/bar.jsonl.meta.json`` — sidecar holding content type and
      user metadata.

    Writes are atomic: the payload is first written to a temporary file in
    the same directory and then moved into place via :func:`os.replace`. This
    matches Azure Blob's "no partial reads" guarantee for the local target.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        """Absolute path of the directory holding all managed blobs."""
        return self._root

    def put(
        self,
        key: str,
        data: BlobData,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[Mapping[str, str]] = None,
    ) -> BlobMetadata:
        normalize_key(key)
        payload = bytes(data)
        target = self._resolve(key)
        meta_path = self._meta_path_for(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        meta_record = {
            "content_type": content_type,
            "metadata": dict(metadata or {}),
        }
        meta_bytes = json.dumps(meta_record, sort_keys=True).encode("utf-8")

        with self._lock:
            self._atomic_write(target, payload)
            self._atomic_write(meta_path, meta_bytes)
            stat = target.stat()

        return BlobMetadata(
            key=key,
            size=len(payload),
            content_type=content_type,
            etag=_etag_for(payload),
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            metadata=dict(metadata or {}),
        )

    def get(self, key: str) -> StoredBlob:
        normalize_key(key)
        target = self._resolve(key)
        if not target.is_file():
            raise BlobNotFoundError(key)
        payload = target.read_bytes()
        meta = self._read_sidecar(target)
        stat = target.stat()
        return StoredBlob(
            data=payload,
            metadata=BlobMetadata(
                key=key,
                size=len(payload),
                content_type=meta.get("content_type"),
                etag=_etag_for(payload),
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                metadata=dict(meta.get("metadata") or {}),
            ),
        )

    def list(self, prefix: str = "") -> Iterator[BlobMetadata]:
        prefix_path = self._root if not prefix else (self._root / prefix)
        if prefix and not str(prefix_path.resolve()).startswith(str(self._root)):
            raise ValueError(f"prefix escapes storage root: {prefix!r}")

        # When the prefix targets a single file (no trailing slash) the
        # caller still gets it back through the directory walk below.
        scan_root = prefix_path if prefix_path.is_dir() else prefix_path.parent
        if not scan_root.exists():
            return iter(())

        return self._walk(scan_root, prefix)

    def delete(self, key: str) -> None:
        normalize_key(key)
        target = self._resolve(key)
        meta_path = self._meta_path_for(target)
        with self._lock:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            try:
                meta_path.unlink()
            except FileNotFoundError:
                pass

    def exists(self, key: str) -> bool:
        normalize_key(key)
        return self._resolve(key).is_file()

    def health_check(self) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if not os.access(self._root, os.W_OK):
                raise StorageError(f"storage root is not writable: {self._root}")
        except OSError as exc:
            raise StorageError(f"local storage unreachable: {exc}") from exc

    def _resolve(self, key: str) -> Path:
        target = (self._root / key).resolve()
        if not str(target).startswith(str(self._root)):
            raise ValueError(f"key escapes storage root: {key!r}")
        return target

    def _meta_path_for(self, payload_path: Path) -> Path:
        return payload_path.with_name(payload_path.name + _METADATA_SUFFIX)

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        try:
            with os.fdopen(tmp_fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise

    def _read_sidecar(self, payload_path: Path) -> dict:
        meta_path = self._meta_path_for(payload_path)
        if not meta_path.is_file():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _walk(self, scan_root: Path, prefix: str) -> Iterator[BlobMetadata]:
        for path in sorted(scan_root.rglob("*")):
            if not path.is_file():
                continue
            if path.name.endswith(_METADATA_SUFFIX):
                continue
            relative = path.relative_to(self._root).as_posix()
            if prefix and not relative.startswith(prefix):
                continue
            payload = path.read_bytes()
            meta = self._read_sidecar(path)
            stat = path.stat()
            yield BlobMetadata(
                key=relative,
                size=len(payload),
                content_type=meta.get("content_type"),
                etag=_etag_for(payload),
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                metadata=dict(meta.get("metadata") or {}),
            )


def _etag_for(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
