"""Authentication and authorization for the Argox Collector (COL-09).

Two credential flows over a single ``Authorization: Bearer`` header:

- **API keys** (machine-to-machine, SDK -> Collector): scoped, revocable,
  stored hashed in the index DB.
- **OIDC JWTs** (human, dashboard -> Collector): validated against a
  configurable IdP, with a role claim driving RBAC.

Routes enforce access with the :func:`require_scope` dependency; health and
readiness probes stay public.
"""

from argox_collector.auth.authenticator import Authenticator
from argox_collector.auth.dependencies import require_scope
from argox_collector.auth.factory import (
    build_api_key_store,
    build_authenticator,
    build_oidc_validator,
)
from argox_collector.auth.keys import (
    KEY_PREFIX,
    ApiKeyRecord,
    NewApiKey,
    generate_key,
    hash_key,
    mint_key,
)
from argox_collector.auth.keystore import ApiKeyStore, ApiKeyStoreError
from argox_collector.auth.oidc import OidcError, OidcValidator
from argox_collector.auth.principal import (
    Principal,
    PrincipalKind,
    Scope,
    parse_scopes,
)

__all__ = [
    "Authenticator",
    "require_scope",
    "build_api_key_store",
    "build_authenticator",
    "build_oidc_validator",
    "KEY_PREFIX",
    "ApiKeyRecord",
    "NewApiKey",
    "generate_key",
    "hash_key",
    "mint_key",
    "ApiKeyStore",
    "ApiKeyStoreError",
    "OidcError",
    "OidcValidator",
    "Principal",
    "PrincipalKind",
    "Scope",
    "parse_scopes",
]
