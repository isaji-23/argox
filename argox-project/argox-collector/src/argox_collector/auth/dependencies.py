"""FastAPI dependencies that gate routes on authentication and scope (COL-09).

Routers attach ``Depends(require_scope(Scope.X))`` either as a route-level
dependency (when the handler does not need the identity) or as a parameter
``principal: Principal = Depends(require_scope(Scope.X))`` (when it does, e.g.
to bind the audit ``actor`` to the caller).
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request

from argox_collector.auth.authenticator import Authenticator
from argox_collector.auth.principal import Principal, Scope


def _authenticator(request: Request) -> Authenticator:
    return request.app.state.auth


def require_scope(scope: Scope) -> Callable[[Request], Principal]:
    """Return a dependency that authenticates the request and requires ``scope``.

    The returned dependency yields the resolved :class:`Principal`, so handlers
    that need the caller's identity can depend on it directly.
    """

    def dependency(request: Request) -> Principal:
        return _authenticator(request).authenticate(request, scope)

    return dependency
