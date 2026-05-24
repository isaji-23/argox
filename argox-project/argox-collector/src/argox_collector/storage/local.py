"""Local filesystem implementation of :class:`StorageBackend`."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from argox_collector.storage.base import (
    BlobData,
    BlobMetadata,
    BlobNotFoundError,
    StorageBackend,
    StorageError,
    StoredBlob,
    normalize_key,
    normalize_prefix,
    validate_metadata,
)

_METADATA_SUFFIX = ".meta.json"
# Filenames the backend creates for its own bookkeeping. They live under the
# storage root but are never blobs, so listings must skip them and ``put``
# must never accept a key that would collide with them.
_TMP_PREFIX = ".tmp-"
_HEALTH_PREFIX = ".argox-health-"


def _is_internal_name(name: str) -> bool:
    """Return ``True`` for backend bookkeeping files that are not blobs."""
    return (
        name.endswith(_METADATA_SUFFIX)
        or name.startswith(_TMP_PREFIX)
        or name.startswith(_HEALTH_PREFIX)
    )


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
        clean_metadata = validate_metadata(metadata)
        payload = bytes(data)
        target = self._resolve(key)
        meta_path = self._meta_path_for(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        meta_record = {
            "content_type": content_type,
            "metadata": clean_metadata,
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
            metadata=clean_metadata,
        )

    def get(self, key: str) -> StoredBlob:
        normalize_key(key)
        target = self._resolve(key)
        # Read payload and sidecar under the write lock so a concurrent
        # ``put`` (which holds the same lock across both atomic writes) can
        # never expose a new payload paired with a stale sidecar, and a
        # concurrent ``delete`` surfaces as ``BlobNotFoundError`` rather than
        # a raw ``FileNotFoundError``.
        with self._lock:
            try:
                payload = target.read_bytes()
                stat = target.stat()
            except FileNotFoundError:
                raise BlobNotFoundError(key) from None
            meta = self._read_sidecar(target)
        content_type, metadata = _sidecar_fields(meta)
        return StoredBlob(
            data=payload,
            metadata=BlobMetadata(
                key=key,
                size=len(payload),
                content_type=content_type,
                etag=_etag_for(payload),
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                metadata=metadata,
            ),
        )

    def list(self, prefix: str = "") -> Iterator[BlobMetadata]:
        # String-prefix semantics matching the Azure driver and the
        # StorageBackend contract: a key matches when it *starts with* the
        # prefix, including partial trailing segments (``spans/2024/0`` matches
        # ``spans/2024/01.jsonl``). To stay O(matching subtree) rather than
        # O(total files), scan only the deepest fully-named directory implied
        # by the prefix and filter entries by ``startswith``.
        normalize_prefix(prefix)
        if not prefix:
            yield from self._walk(self._root, "")
            return

        # ``head`` is the directory portion of the prefix; the remainder is a
        # partial filename used purely as a ``startswith`` filter. A trailing
        # slash means the whole prefix names a directory.
        head = prefix.rstrip("/") if prefix.endswith("/") else prefix.rpartition("/")[0]
        scan_root = (self._root / head).resolve() if head else self._root
        if not _is_inside(scan_root, self._root):
            raise ValueError(f"prefix escapes storage root: {prefix!r}")
        if not scan_root.is_dir():
            # Nothing under the implied directory: no key can match.
            return
        yield from self._walk(scan_root, prefix)

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
                prefix=_HEALTH_PREFIX, dir=self._root
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
        if _is_internal_name(target.name):
            # A key whose basename matches a sidecar/temp/health-probe name
            # would collide with backend bookkeeping (e.g. ``foo.meta.json``
            # is the sidecar of ``foo``) and be hidden from ``list``.
            raise ValueError(
                f"blob key collides with backend bookkeeping files: {key!r}"
            )
        return target

    def _meta_path_for(self, payload_path: Path) -> Path:
        return payload_path.with_name(payload_path.name + _METADATA_SUFFIX)

    def _atomic_write(self, target: Path, payload: bytes) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(prefix=_TMP_PREFIX, dir=target.parent)
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
        try:
            raw = meta_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _walk(self, scan_root: Path, prefix: str) -> Iterator[BlobMetadata]:
        # Stream entries via os.scandir; never read payload bytes here. etag
        # is intentionally omitted in listings — callers that need it should
        # `get()` the blob, since computing it requires hashing the payload.
        for path in _scan_files(scan_root):
            # Skip sidecars and the backend's own temp/health-probe files: a
            # ``list`` racing a ``put``/``health_check`` must never surface
            # these transient internals as blobs.
            if _is_internal_name(path.name):
                continue
            relative = path.relative_to(self._root).as_posix()
            if prefix and not relative.startswith(prefix):
                continue
            try:
                meta = self._read_sidecar(path)
                stat = path.stat()
            except FileNotFoundError:
                # Concurrent delete removed the blob mid-scan; skip it rather
                # than aborting the whole listing.
                continue
            content_type, metadata = _sidecar_fields(meta)
            yield BlobMetadata(
                key=relative,
                size=stat.st_size,
                content_type=content_type,
                etag=None,
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                metadata=metadata,
            )


def _scan_files(root: Path) -> Iterator[Path]:
    """Yield every regular file under ``root`` without materializing the list.

    Tolerates concurrent deletes: directories or entries that vanish mid-scan
    are skipped instead of raising ``FileNotFoundError``.
    """
    try:
        scanner = os.scandir(root)
    except FileNotFoundError:
        return
    with scanner:
        for entry in scanner:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except FileNotFoundError:
                continue
            if is_dir:
                yield from _scan_files(Path(entry.path))
            elif is_file:
                yield Path(entry.path)


def _sidecar_fields(meta: Mapping[str, Any]) -> tuple[Optional[str], dict[str, str]]:
    """Extract ``content_type`` and ``metadata`` from a sidecar record safely.

    Sidecars can be hand-edited or corrupted, so the inner fields are not
    trusted: ``content_type`` is dropped unless it is a string, and
    ``metadata`` is filtered down to ASCII ``str``->``str`` items (mirroring
    :func:`validate_metadata` but without raising) so the result always honors
    the ``BlobMetadata.metadata: Mapping[str, str]`` contract. Anything else
    falls back to ``{}``. This keeps a bad sidecar from raising
    ``TypeError``/``ValueError`` and crashing reads or listings.
    """
    content_type = meta.get("content_type")
    if not isinstance(content_type, str):
        content_type = None
    raw_metadata = meta.get("metadata")
    metadata: dict[str, str] = {}
    if isinstance(raw_metadata, Mapping):
        for key, value in raw_metadata.items():
            if (
                isinstance(key, str)
                and isinstance(value, str)
                and key.isascii()
                and value.isascii()
            ):
                metadata[key] = value
    return content_type, metadata


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
