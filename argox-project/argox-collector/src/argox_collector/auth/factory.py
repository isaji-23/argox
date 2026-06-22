"""Build auth components from :class:`CollectorSettings` (COL-09)."""

from __future__ import annotations

from typing import Optional

import structlog

from argox_collector.auth.authenticator import Authenticator
from argox_collector.auth.keystore import ApiKeyStore
from argox_collector.auth.oidc import OidcValidator
from argox_collector.settings import CollectorSettings

logger = structlog.get_logger(__name__)


def build_api_key_store(settings: CollectorSettings) -> ApiKeyStore:
    """Open the API key store on the configured index DB path."""
    return ApiKeyStore(db_path=settings.index_duckdb_path)


def build_oidc_validator(
    settings: CollectorSettings,
) -> Optional[OidcValidator]:
    """Construct an OIDC validator when the IdP is configured, else ``None``.

    Requires ``oidc_issuer``, ``oidc_audience`` and ``oidc_jwks_uri`` together;
    a partial configuration is treated as "OIDC disabled" and logged so a typo
    does not silently enable a half-configured validator.
    """
    issuer = settings.oidc_issuer
    audience = settings.oidc_audience
    jwks_uri = settings.oidc_jwks_uri
    if not any((issuer, audience, jwks_uri)):
        return None
    if not all((issuer, audience, jwks_uri)):
        logger.warning(
            "oidc_config_incomplete",
            has_issuer=bool(issuer),
            has_audience=bool(audience),
            has_jwks_uri=bool(jwks_uri),
        )
        return None
    return OidcValidator(
        issuer=issuer,
        audience=audience,
        jwks_uri=jwks_uri,
        role_claim=settings.oidc_role_claim,
        policy_write_role=settings.oidc_policy_write_role,
        admin_role=settings.oidc_admin_role,
    )


def build_authenticator(
    settings: CollectorSettings,
    *,
    key_store: Optional[ApiKeyStore] = None,
) -> Authenticator:
    """Assemble the :class:`Authenticator` for the app.

    ``key_store`` is injected by the app factory (it owns the store's lifecycle);
    the OIDC validator is built here from settings.
    """
    oidc = build_oidc_validator(settings) if settings.auth_enabled else None
    return Authenticator(
        enabled=settings.auth_enabled,
        key_store=key_store,
        oidc=oidc,
        bootstrap_admin_key=settings.bootstrap_admin_key,
    )
