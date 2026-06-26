"""Shared networking helpers for the SDK clients that send credentials."""

from __future__ import annotations

from urllib.parse import urlsplit

# Hosts where traffic never leaves the machine, so a Bearer token sent over
# plain HTTP is not actually exposed on the wire.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_plaintext_credential_endpoint(endpoint: str) -> bool:
    """Return True when sending a credential to ``endpoint`` exposes it in plaintext.

    A credential is exposed when the endpoint is not HTTPS *and* the host is not
    a loopback address. Loopback traffic never reaches the network, so an HTTP
    token there is not a leak — warning on it only adds noise to the common
    local-development flow.

    Args:
        endpoint: The target URL (e.g. ``http://localhost:4318/v1/traces``).

    Returns:
        True if a warning about plaintext credential exposure is warranted.
    """
    parts = urlsplit(endpoint)
    if parts.scheme == "https":
        return False
    return (parts.hostname or "").lower() not in _LOOPBACK_HOSTS
