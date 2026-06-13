"""OIDC JWT validation and role-based scope mapping (COL-09).

Dashboard users authenticate to their IdP (Microsoft Entra ID by default, or any
generic OIDC provider) through the OAuth2 authorization-code flow handled by the
dashboard. The dashboard then calls the Collector with the resulting JWT as a
bearer token. This module verifies that token — signature against the IdP's
JWKS, plus issuer, audience and expiry — and maps its role claim to Argox
:class:`Scope` values for RBAC.

Verification keys come from the IdP's JWKS endpoint via :class:`jwt.PyJWKClient`,
which fetches and caches the signing keys. Tests inject a static public key
instead of reaching the network.
"""

from __future__ import annotations

from typing import Iterable, Optional

import jwt
import structlog
from jwt import PyJWKClient

from argox_collector.auth.principal import Principal, PrincipalKind, Scope

logger = structlog.get_logger(__name__)


class OidcError(Exception):
    """Raised when a JWT cannot be validated."""


# Tolerance (seconds) applied to exp/nbf/iat to absorb IdP/Collector clock drift.
_CLOCK_SKEW_LEEWAY_S = 60

# Scopes every authenticated human gets, before any role escalation. The
# dashboard is a read surface plus the policy editor, so a baseline user can
# read traces/metrics and view policies; mutating policies needs a role.
_BASE_SCOPES = frozenset({Scope.READ, Scope.POLICY_READ})


class OidcValidator:
    """Validate IdP-issued JWTs and resolve them to a :class:`Principal`."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_uri: Optional[str] = None,
        role_claim: str = "roles",
        policy_write_role: Optional[str] = None,
        admin_role: Optional[str] = None,
        public_key: Optional[object] = None,
        algorithms: Optional[Iterable[str]] = None,
    ) -> None:
        """Build a validator.

        Provide ``jwks_uri`` for real deployments (keys are fetched and rotated
        from the IdP), or ``public_key`` to verify against a fixed key (used by
        tests to act as the IdP without a network round-trip). Exactly one of
        the two must be supplied.
        """
        if bool(jwks_uri) == bool(public_key):
            raise ValueError("supply exactly one of jwks_uri or public_key")
        self._issuer = issuer
        self._audience = audience
        self._role_claim = role_claim
        self._policy_write_role = policy_write_role
        self._admin_role = admin_role
        self._public_key = public_key
        self._algorithms = list(algorithms or ["RS256"])
        self._jwk_client = PyJWKClient(jwks_uri) if jwks_uri else None

    def validate(self, token: str) -> Principal:
        """Verify ``token`` and return the principal it represents.

        Raises:
            OidcError: If the signature, issuer, audience or expiry is invalid,
                or the token is otherwise malformed.
        """
        try:
            key = self._signing_key(token)
            claims = jwt.decode(
                token,
                key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                # Small leeway absorbs clock drift between the IdP and the
                # Collector so valid tokens are not rejected at the exp/nbf
                # boundary (intermittent 401s otherwise).
                leeway=_CLOCK_SKEW_LEEWAY_S,
                options={"require": ["exp", "iss", "aud"]},
            )
        except OidcError:
            raise
        except jwt.PyJWTError as exc:
            # Verification failures are logged with detail but surfaced as a
            # single opaque error: the caller only ever returns 401.
            logger.info("oidc_token_rejected", error=str(exc))
            raise OidcError(str(exc)) from exc

        subject = claims.get("sub")
        if not subject:
            raise OidcError("token missing 'sub' claim")
        scopes = self._scopes_for(self._roles(claims))
        return Principal(
            subject=subject,
            kind=PrincipalKind.OIDC,
            scopes=scopes,
            display_name=claims.get("name") or claims.get("preferred_username"),
        )

    def _signing_key(self, token: str):
        if self._public_key is not None:
            return self._public_key
        assert self._jwk_client is not None  # guaranteed by __init__
        try:
            return self._jwk_client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            logger.info("oidc_jwks_lookup_failed", error=str(exc))
            raise OidcError(f"could not resolve signing key: {exc}") from exc

    def _roles(self, claims: dict) -> frozenset[str]:
        raw = claims.get(self._role_claim)
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            # Some IdPs emit a space-delimited string instead of a JSON array.
            return frozenset(raw.split())
        if isinstance(raw, (list, tuple)):
            return frozenset(str(item) for item in raw)
        return frozenset()

    def _scopes_for(self, roles: frozenset[str]) -> frozenset[Scope]:
        scopes = set(_BASE_SCOPES)
        if self._policy_write_role and self._policy_write_role in roles:
            scopes.add(Scope.POLICY_WRITE)
        if self._admin_role and self._admin_role in roles:
            scopes.add(Scope.ADMIN)
        return frozenset(scopes)
