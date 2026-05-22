"""Azure Blob Storage implementation of :class:`StorageBackend`.

The production target for the Collector is Azure Blob Storage. Development
parity is provided by `Azurite <https://learn.microsoft.com/azure/storage/common/storage-use-azurite>`_,
which speaks the same protocol; the test suite exercises this backend through
mocks so it does not require a running emulator.

``azure-storage-blob`` is imported lazily so that deployments that only use
the local driver are not forced to pull in the Azure SDK.
"""

from __future__ import annotations

from types import SimpleNamespace
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


class AzureBlobStorageBackend(StorageBackend):
    """Persist blobs to an Azure Blob Storage container.

    The backend operates on a single container and treats blob names as
    forward-slash separated paths — mirroring how the design document
    describes layout (``spans/{YYYY}/{MM}/{DD}/{HH}/{batch_id}.jsonl``).

    Args:
        container_client: A configured ``azure.storage.blob.ContainerClient``.
            Supplying the client directly keeps the backend test-friendly:
            production code wires it from a connection string via
            :meth:`from_connection_string`, while tests inject a stub.
        container_name: Name of the underlying container, kept for logging.
    """

    def __init__(self, container_client: Any, container_name: str) -> None:
        self._container = container_client
        self._container_name = container_name

    @classmethod
    def from_connection_string(
        cls, connection_string: str, container_name: str
    ) -> "AzureBlobStorageBackend":
        """Build a backend from a standard Azure connection string."""
        try:
            from azure.core.exceptions import ResourceExistsError
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:  # pragma: no cover - exercised via factory
            raise StorageError(
                "azure-storage-blob is required for AzureBlobStorageBackend; "
                "install argox-collector[azure] to enable it"
            ) from exc

        service = BlobServiceClient.from_connection_string(connection_string)
        container = service.get_container_client(container_name)
        try:
            container.create_container()
        except ResourceExistsError:
            pass
        except Exception as exc:
            raise StorageError(
                f"failed to ensure container {container_name!r}: {exc}"
            ) from exc
        return cls(container_client=container, container_name=container_name)

    @property
    def container_name(self) -> str:
        return self._container_name

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
        blob = self._container.get_blob_client(key)
        content_settings = _build_content_settings(content_type)
        try:
            result = blob.upload_blob(
                payload,
                overwrite=True,
                content_settings=content_settings,
                metadata=dict(metadata or {}),
            )
        except Exception as exc:
            raise StorageError(f"failed to upload {key!r}: {exc}") from exc

        etag = _strip_quotes(_attr(result, "etag", None))
        last_modified = _attr(result, "last_modified", None)
        return BlobMetadata(
            key=key,
            size=len(payload),
            content_type=content_type,
            etag=etag,
            last_modified=last_modified,
            metadata=dict(metadata or {}),
        )

    def get(self, key: str) -> StoredBlob:
        normalize_key(key)
        blob = self._container.get_blob_client(key)
        try:
            downloader = blob.download_blob()
            payload = downloader.readall()
            properties = downloader.properties
        except Exception as exc:
            if _is_not_found(exc):
                raise BlobNotFoundError(key) from exc
            raise StorageError(f"failed to fetch {key!r}: {exc}") from exc

        return StoredBlob(
            data=bytes(payload),
            metadata=_metadata_from_properties(key, properties, len(payload)),
        )

    def list(self, prefix: str = "") -> Iterator[BlobMetadata]:
        try:
            iterator = self._container.list_blobs(name_starts_with=prefix or None)
        except Exception as exc:
            raise StorageError(f"failed to list prefix {prefix!r}: {exc}") from exc
        for blob in iterator:
            yield _metadata_from_properties(
                key=_attr(blob, "name", ""),
                properties=blob,
                size=_attr(blob, "size", 0),
            )

    def delete(self, key: str) -> None:
        normalize_key(key)
        blob = self._container.get_blob_client(key)
        try:
            blob.delete_blob()
        except Exception as exc:
            if _is_not_found(exc):
                return
            raise StorageError(f"failed to delete {key!r}: {exc}") from exc

    def exists(self, key: str) -> bool:
        normalize_key(key)
        blob = self._container.get_blob_client(key)
        try:
            return bool(blob.exists())
        except Exception as exc:
            raise StorageError(f"failed to probe {key!r}: {exc}") from exc

    def health_check(self) -> None:
        try:
            self._container.get_container_properties()
        except Exception as exc:
            raise StorageError(
                f"azure container {self._container_name!r} unreachable: {exc}"
            ) from exc


def _build_content_settings(content_type: Optional[str]) -> Any:
    if content_type is None:
        return None
    try:
        from azure.storage.blob import ContentSettings
    except ImportError:  # pragma: no cover - exercised when SDK is absent
        # Fall back to a lightweight stand-in so injected fake clients still
        # observe the content type via attribute access. The real SDK code
        # path uses ContentSettings; this branch only matters in tests that
        # run without the ``azure`` extra installed.
        return SimpleNamespace(content_type=content_type)
    return ContentSettings(content_type=content_type)


def _metadata_from_properties(
    key: str, properties: Any, size: int
) -> BlobMetadata:
    content_settings = _attr(properties, "content_settings", None)
    content_type = (
        _attr(content_settings, "content_type", None)
        if content_settings is not None
        else None
    )
    return BlobMetadata(
        key=key,
        size=int(_attr(properties, "size", size) or size),
        content_type=content_type,
        etag=_strip_quotes(_attr(properties, "etag", None)),
        last_modified=_attr(properties, "last_modified", None),
        metadata=dict(_attr(properties, "metadata", {}) or {}),
    )


def _attr(obj: Any, name: str, default: Any) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _strip_quotes(etag: Optional[str]) -> Optional[str]:
    if etag is None:
        return None
    return etag.strip('"')


def _is_not_found(exc: BaseException) -> bool:
    error_code = getattr(exc, "error_code", None)
    if error_code in {"BlobNotFound", "ContainerNotFound"}:
        return True
    status_code = getattr(exc, "status_code", None)
    return status_code == 404
