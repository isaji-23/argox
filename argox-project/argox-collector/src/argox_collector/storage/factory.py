"""Build a :class:`StorageBackend` from :class:`CollectorSettings`."""

from __future__ import annotations

from argox_collector.settings import CollectorSettings
from argox_collector.storage.azure import AzureBlobStorageBackend
from argox_collector.storage.base import StorageBackend, StorageError
from argox_collector.storage.local import LocalStorageBackend


def build_storage(settings: CollectorSettings) -> StorageBackend:
    """Return the storage backend selected by ``settings``.

    Args:
        settings: Collector configuration; ``storage_backend`` and the
            backend-specific fields select the driver.

    Raises:
        StorageError: If the requested backend is misconfigured (e.g. the
            Azure driver is selected without a connection string).
    """
    backend = settings.storage_backend.lower()
    if backend == "local":
        return LocalStorageBackend(root=settings.storage_local_root)
    if backend == "azure":
        if not settings.storage_azure_connection_string:
            raise StorageError(
                "ARGOX_STORAGE_AZURE_CONNECTION_STRING must be set when "
                "ARGOX_STORAGE_BACKEND=azure"
            )
        return AzureBlobStorageBackend.from_connection_string(
            connection_string=settings.storage_azure_connection_string,
            container_name=settings.storage_azure_container,
        )
    raise StorageError(f"unknown storage backend: {settings.storage_backend!r}")
