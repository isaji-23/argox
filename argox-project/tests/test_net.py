"""Tests for the shared credential-endpoint networking helper."""

from __future__ import annotations

import pytest

from argox.net import is_plaintext_credential_endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://collector.example.com/v1/traces",
        "http://collector.example.com:4318",
        "HTTP://Collector.Example.Com/policy",
    ],
)
def test_remote_http_endpoint_is_plaintext(endpoint: str) -> None:
    """Non-HTTPS endpoints to a remote host expose the credential."""
    assert is_plaintext_credential_endpoint(endpoint) is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://collector.example.com/v1/traces",
        "https://localhost:4318/v1/traces",
    ],
)
def test_https_endpoint_is_not_plaintext(endpoint: str) -> None:
    """HTTPS endpoints never expose the credential regardless of host."""
    assert is_plaintext_credential_endpoint(endpoint) is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:4318/v1/traces",
        "http://127.0.0.1:8000/api/v1/policies/bundle",
        "http://[::1]:4318/v1/traces",
    ],
)
def test_loopback_http_endpoint_is_not_plaintext(endpoint: str) -> None:
    """Plain-HTTP loopback traffic never leaves the machine, so it is not a leak."""
    assert is_plaintext_credential_endpoint(endpoint) is False
