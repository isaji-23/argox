"""Abstract :class:`StorageBackend` interface and shared value objects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator, Mapping, Optional, Union

BlobData = Union[bytes, bytearray, memoryview]
"""Raw payload types accepted by :meth:`StorageBackend.put`."""


class StorageError(RuntimeError):
    """Base class for storage backend failures."""


class BlobNotFoundError(StorageError):
    """Raised when :meth:`StorageBackend.get` is called for a missing key."""

    def __init__(self, key: str) -> None:
        super().__init__(f"blob not found: {key!r}")
        self.key = key


@dataclass(frozen=True)
class BlobMetadata:
    """Lightweight descriptor returned by ``put``/``list``.

    Attributes:
        key: Hierarchical name of the blob (forward-slash separated).
        size: Payload size in bytes.
        content_type: MIME type recorded on write, when supplied.
        etag: Backend-assigned identifier used for concurrency control.
            Local backend derives this from the file's content hash.
        last_modified: Wall-clock timestamp of the most recent write,
            ``None`` if the backend cannot report it.
        metadata: User-defined key/value pairs stored alongside the blob.
    """

    key: str
    size: int
    content_type: Optional[str] = None
    etag: Optional[str] = None
    last_modified: Optional[datetime] = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredBlob:
    """A blob payload returned by :meth:`StorageBackend.get`."""

    data: bytes
    metadata: BlobMetadata


class StorageBackend(ABC):
    """Abstract interface for the Collector's blob store.

    Implementations are expected to be safe for concurrent use from multiple
    threads — the Collector calls them from FastAPI's threadpool when serving
    ingest requests. All operations are synchronous; async wrappers can be
    layered on top by callers that need them.
    """

    @abstractmethod
    def put(
        self,
        key: str,
        data: BlobData,
        *,
        content_type: Optional[str] = None,
        metadata: Optional[Mapping[str, str]] = None,
    ) -> BlobMetadata:
        """Write ``data`` to ``key`` and return its metadata.

        Existing blobs at the same key are overwritten. Implementations must
        treat the operation as atomic from the perspective of concurrent
        readers: a partial payload is never observable.

        Args:
            key: Forward-slash separated blob path. Leading slashes are not
                permitted.
            data: Raw bytes to persist.
            content_type: Optional MIME type recorded alongside the blob.
            metadata: Optional user metadata. Keys and values must be ASCII;
                backends may impose additional limits.

        Returns:
            Metadata describing the persisted blob.
        """

    @abstractmethod
    def get(self, key: str) -> StoredBlob:
        """Return the blob at ``key``.

        Raises:
            BlobNotFoundError: If no blob exists at ``key``.
        """

    @abstractmethod
    def list(self, prefix: str = "") -> Iterator[BlobMetadata]:
        """Yield metadata for every blob whose key begins with ``prefix``.

        Order is not guaranteed. Implementations should stream results lazily
        so the caller can break early without paying for the full listing.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the blob at ``key`` if it exists.

        Deleting a missing blob is a no-op; callers that need to assert
        existence should call :meth:`exists` first.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return ``True`` when a blob is stored at ``key``."""

    def health_check(self) -> None:
        """Verify the backend is reachable.

        Default implementation issues a no-op ``list`` against an unlikely
        prefix. Subclasses may override to ping their underlying service
        more directly.

        Raises:
            StorageError: If the backend is unreachable or misconfigured.
        """
        try:
            iterator = self.list(prefix="__argox_health_check__/")
            next(iter(iterator), None)
        except StorageError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise StorageError(f"health check failed: {exc}") from exc


def normalize_key(key: str) -> str:
    """Validate and normalize a blob key.

    Empty keys, absolute paths and parent-directory traversal segments are
    rejected so that local-filesystem drivers cannot be tricked into writing
    outside their root.
    """
    if not key:
        raise ValueError("blob key must not be empty")
    if key.startswith("/"):
        raise ValueError(f"blob key must be relative: {key!r}")
    parts = key.split("/")
    if any(segment in {"", ".", ".."} for segment in parts):
        raise ValueError(f"blob key contains invalid segment: {key!r}")
    return key
