"""Storage backend abstraction for the Argox Collector.

The Collector persists authoritative state (span batches, policy bundles,
audit-log segments) to a blob store. Production runs on Azure Blob Storage;
development and CI use the local filesystem. Both implementations satisfy a
single :class:`StorageBackend` interface so the rest of the service is
agnostic to the underlying driver.
"""

from argox_collector.storage.azure import AzureBlobStorageBackend
from argox_collector.storage.base import (
    BlobMetadata,
    BlobNotFoundError,
    ConditionNotMetError,
    StorageBackend,
    StorageError,
    StoredBlob,
)
from argox_collector.storage.factory import build_storage
from argox_collector.storage.local import LocalStorageBackend

__all__ = [
    "AzureBlobStorageBackend",
    "BlobMetadata",
    "BlobNotFoundError",
    "ConditionNotMetError",
    "LocalStorageBackend",
    "StorageBackend",
    "StorageError",
    "StoredBlob",
    "build_storage",
]
