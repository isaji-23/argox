"""Authorization primitives: scopes and the authenticated principal (COL-09).

A :class:`Principal` is the resolved identity behind a request, regardless of
which credential carried it (an API key for SDK clients or an OIDC JWT for
dashboard users). It carries the set of :class:`Scope` values the credential
grants; routers gate access by asking the principal whether it holds a scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Iterable


class Scope(str, Enum):
    """Permission a credential may grant.

    ``ADMIN`` is a super-scope: a principal holding it satisfies every
    :meth:`Principal.has_scope` check, so admin credentials never need the
    individual scopes enumerated alongside it.
    """

    INGEST = "ingest"
    POLICY_READ = "policy-read"
    POLICY_WRITE = "policy-write"
    READ = "read"
    ADMIN = "admin"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


def parse_scopes(values: Iterable[str]) -> FrozenSet[Scope]:
    """Parse raw scope strings into :class:`Scope` values.

    Raises:
        ValueError: If any string is not a recognised scope.
    """
    result = set()
    for value in values:
        try:
            result.add(Scope(value))
        except ValueError as exc:
            valid = ", ".join(s.value for s in Scope)
            raise ValueError(
                f"unknown scope {value!r}; valid scopes: {valid}"
            ) from exc
    return frozenset(result)


class PrincipalKind(str, Enum):
    """Origin of an authenticated identity."""

    API_KEY = "api_key"
    OIDC = "oidc"
    ANONYMOUS = "anonymous"


@dataclass(frozen=True)
class Principal:
    """An authenticated identity and the scopes it is granted.

    Attributes:
        subject: Stable identifier for the caller — the API key id for machine
            credentials, or the JWT ``sub`` claim for human users. This is what
            gets recorded as the ``actor`` on audit entries.
        kind: Which credential family authenticated the request.
        scopes: The permissions granted. An ``ADMIN`` scope implies all others.
        display_name: Human-friendly label for logs/audit, when available
            (a key's name or a token's ``name``/``preferred_username``).
    """

    subject: str
    kind: PrincipalKind
    scopes: FrozenSet[Scope] = field(default_factory=frozenset)
    display_name: str | None = None

    def has_scope(self, scope: Scope) -> bool:
        """Return whether this principal satisfies ``scope``.

        ``ADMIN`` satisfies every scope.
        """
        return Scope.ADMIN in self.scopes or scope in self.scopes

    @classmethod
    def anonymous(cls) -> "Principal":
        """Return the all-scopes principal used when auth is disabled.

        Holding ``ADMIN`` means every scope check passes, so disabling auth is
        a single switch rather than a special case threaded through each route.
        """
        return cls(
            subject="anonymous",
            kind=PrincipalKind.ANONYMOUS,
            scopes=frozenset({Scope.ADMIN}),
        )
