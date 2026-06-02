"""Dependency injection utilities for FastAPI endpoints.

This module provides dependency functions that FastAPI uses to inject
shared resources (storage, index, etc.) into endpoint handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from argox_collector.storage.base import StorageBackend


def get_storage(request: Request) -> StorageBackend:
    """
    Inject the configured storage backend into an endpoint.

    The storage backend is attached to the app state during app initialization
    in :func:`argox_collector.app.create_app`.

    Args:
        request: The FastAPI request object (automatically injected).

    Returns:
        The StorageBackend instance (e.g., LocalStorageBackend, AzureStorageBackend).
    """
    return request.app.state.storage
