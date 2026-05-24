"""Local filesystem implementation of :class:`StorageBackend`."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional

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
        # Keep prefix semantics consistent with ``normalize_key``: forward
        # slashes only and no parent-directory traversal. Unlike a full key,
        # a prefix may be empty or end with a slash, so we cannot reuse
        # ``normalize_key`` verbatim.
        if "\\" in prefix:
            raise ValueError(f"prefix must use forward slashes only: {prefix!r}")
        if ".." in prefix.split("/"):
            raise ValueError(f"prefix contains invalid segment: {prefix!r}")

        prefix_path = self._root if not prefix else (self._root / prefix)
        if prefix and not _is_inside(prefix_path.resolve(), self._root):
            raise ValueError(f"prefix escapes storage root: {prefix!r}")

        if prefix_path.is_dir():
            yield from self._walk(prefix_path, prefix)
            return
        if prefix_path.is_file() and not prefix_path.name.endswith(
            _METADATA_SUFFIX
        ):
            # Non-directory prefix that points at an existing blob: yield
            # just that entry instead of scanning the parent directory.
            yield from self._walk_single(prefix_path)
            return
        # Missing prefix: do not fall back to scanning the parent — that
        # would make a no-op listing O(total files in root).
        return

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
        # Probe the root by creating and deleting a tiny temp file: this is
        # what `put` actually needs and avoids the well-known false
        # positives/negatives of ``os.access`` on directories under POSIX
        # ACLs or container-mount permission quirks.
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(f"local storage unreachable: {exc}") from exc
        try:
            fd, probe_path = tempfile.mkstemp(
                prefix=".argox-health-", dir=self._root
            )
        except OSError as exc:
            raise StorageError(f"local storage not writable: {exc}") from exc
        try:
            os.close(fd)
        finally:
            try:
                os.unlink(probe_path)
            except FileNotFoundError:
                pass

    def _resolve(self, key: str) -> Path:
        target = (self._root / key).resolve()
        if not _is_inside(target, self._root):
            raise ValueError(f"key escapes storage root: {key!r}")
        return target

    def _meta_path_for(self, payload_path: Path) -> Path:
        return payload_path.with_name(payload_path.name + _METADATA_SUFFIX)

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
        try:
            try:
                handle = os.fdopen(tmp_fd, "wb")
            except Exception:
                # Ownership of tmp_fd has not transferred to a file object
                # yet; close it explicitly to avoid leaking the descriptor.
                os.close(tmp_fd)
                raise
            with handle:
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

    def _read_sidecar(self, payload_path: Path) -> dict[str, Any]:
        meta_path = self._meta_path_for(payload_path)
        if not meta_path.is_file():
            return {}
        try:
            parsed = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _walk_single(self, path: Path) -> Iterator[BlobMetadata]:
        relative = path.relative_to(self._root).as_posix()
        meta = self._read_sidecar(path)
        stat = path.stat()
        yield BlobMetadata(
            key=relative,
            size=stat.st_size,
            content_type=meta.get("content_type"),
            etag=None,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            metadata=dict(meta.get("metadata") or {}),
        )

    def _walk(self, scan_root: Path, prefix: str) -> Iterator[BlobMetadata]:
        # Stream entries via os.scandir; never read payload bytes here. etag
        # is intentionally omitted in listings — callers that need it should
        # `get()` the blob, since computing it requires hashing the payload.
        for path in _scan_files(scan_root):
            if path.name.endswith(_METADATA_SUFFIX):
                continue
            relative = path.relative_to(self._root).as_posix()
            if prefix and not relative.startswith(prefix):
                continue
            meta = self._read_sidecar(path)
            stat = path.stat()
            yield BlobMetadata(
                key=relative,
                size=stat.st_size,
                content_type=meta.get("content_type"),
                etag=None,
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                metadata=dict(meta.get("metadata") or {}),
            )


def _scan_files(root: Path) -> Iterator[Path]:
    """Yield every regular file under ``root`` without materializing the list."""
    with os.scandir(root) as scanner:
        for entry in scanner:
            if entry.is_dir(follow_symlinks=False):
                yield from _scan_files(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                yield Path(entry.path)


def _is_inside(candidate: Path, root: Path) -> bool:
    """Return ``True`` when ``candidate`` is ``root`` or one of its descendants."""
    if candidate == root:
        return True
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _etag_for(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
