"""Request authentication and scope enforcement (COL-09).

The :class:`Authenticator` is the single entry point routers use (via the
:func:`~argox_collector.auth.dependencies.require_scope` dependency) to resolve a
request to a :class:`Principal` and assert it holds the required scope. It hides
which credential family authenticated the caller:

- ``Authorization: Bearer argox_...`` -> API key looked up by hash.
- ``Authorization: Bearer <jwt>``     -> OIDC token validated against the IdP.
- An optional bootstrap admin key (from settings) -> admin principal, so the
  first key can be minted and the dashboard configured before any key exists.

When auth is disabled the authenticator short-circuits to an all-scopes
anonymous principal, so every route stays open with one switch.
"""

from __future__ import annotations

import secrets
from typing import Optional

import structlog
from fastapi import HTTPException, Request, status

from argox_collector.auth.keys import KEY_PREFIX, hash_key
from argox_collector.auth.keystore import ApiKeyStore
from argox_collector.auth.oidc import OidcError, OidcValidator
from argox_collector.auth.principal import Principal, PrincipalKind, Scope

logger = structlog.get_logger(__name__)

_BEARER_PREFIX = "bearer "
# WWW-Authenticate value returned with 401s so clients learn the scheme.
_WWW_AUTH = "Bearer"


class Authenticator:
    """Resolve credentials to principals and enforce scopes."""

    def __init__(
        self,
        *,
        enabled: bool,
        key_store: Optional[ApiKeyStore] = None,
        oidc: Optional[OidcValidator] = None,
        bootstrap_admin_key: Optional[str] = None,
    ) -> None:
        self._enabled = enabled
        self._key_store = key_store
        self._oidc = oidc
        # Pre-hash the bootstrap key once so the per-request comparison is a
        # constant-time digest match, never a plaintext compare.
        self._bootstrap_hash = (
            hash_key(bootstrap_admin_key) if bootstrap_admin_key else None
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def authenticate(self, request: Request, required: Scope) -> Principal:
        """Return the authenticated principal, asserting it holds ``required``.

        Raises:
            HTTPException: ``401`` when no valid credential is presented,
                ``403`` when the principal lacks ``required``.
        """
        if not self._enabled:
            return Principal.anonymous()

        credential = self._bearer_token(request)
        if credential is None:
            raise self._unauthenticated("missing bearer credential")

        principal = self._resolve(credential)
        if principal is None:
            raise self._unauthenticated("invalid credential")

        if not principal.has_scope(required):
            logger.info(
                "authz_denied",
                subject=principal.subject,
                kind=principal.kind.value,
                required=required.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing required scope: {required.value}",
            )
        return principal

    def _resolve(self, credential: str) -> Optional[Principal]:
        # Bootstrap admin key first: a single constant-time digest comparison,
        # no DB hit. Lets the first real key be minted over HTTP.
        if self._bootstrap_hash is not None and secrets.compare_digest(
            hash_key(credential), self._bootstrap_hash
        ):
            return Principal(
                subject="bootstrap-admin",
                kind=PrincipalKind.API_KEY,
                scopes=frozenset({Scope.ADMIN}),
                display_name="bootstrap admin key",
            )

        if credential.startswith(KEY_PREFIX):
            return self._resolve_api_key(credential)
        return self._resolve_oidc(credential)

    def _resolve_api_key(self, credential: str) -> Optional[Principal]:
        if self._key_store is None:
            return None
        record = self._key_store.get_by_hash(hash_key(credential))
        if record is None or not record.is_active():
            return None
        return Principal(
            subject=record.id,
            kind=PrincipalKind.API_KEY,
            scopes=record.scopes,
            display_name=record.name,
        )

    def _resolve_oidc(self, credential: str) -> Optional[Principal]:
        if self._oidc is None:
            return None
        try:
            return self._oidc.validate(credential)
        except OidcError:
            return None

    @staticmethod
    def _bearer_token(request: Request) -> Optional[str]:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith(_BEARER_PREFIX):
            return None
        token = header[len(_BEARER_PREFIX) :].strip()
        return token or None

    @staticmethod
    def _unauthenticated(detail: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": _WWW_AUTH},
        )
