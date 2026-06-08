"""ASGI middleware for the Argox Collector."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)

# Methods that may carry a request body and therefore need size enforcement.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

Scope = dict
Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class PayloadSizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes`` with ``413``.

    Implemented as a pure ASGI middleware so it can abort *while* reading the
    body, rather than after the whole payload has been buffered. This bounds
    peak memory at roughly ``max_bytes`` per in-flight request even for clients
    that omit ``Content-Length`` and stream the body with chunked transfer
    encoding (which a header-only check cannot defend against).

    The ``Content-Length`` header, when present and oversized, is used for a
    fast rejection before any body byte is read.
    """

    def __init__(self, app: Callable, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        if self._content_length_exceeds(scope):
            await self._send_413(send)
            return

        # Buffer the body with early abort. We read at most one chunk past the
        # limit before rejecting, so memory stays bounded by ``max_bytes`` plus
        # a single chunk.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                # Client went away mid-upload; nothing more to serve.
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._send_413(send)
                return
            if not message.get("more_body", False):
                break

        buffered = bytes(body)
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {
                    "type": "http.request",
                    "body": buffered,
                    "more_body": False,
                }
            # The full body was delivered in one message; any further pull
            # should block on the real transport (e.g. for disconnects).
            return await receive()

        await self.app(scope, replay_receive, send)

    def _content_length_exceeds(self, scope: Scope) -> bool:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value) > self.max_bytes
                except ValueError:
                    return False
        return False

    async def _send_413(self, send: Send) -> None:
        body = json.dumps(
            {"error": f"payload exceeds maximum size of {self.max_bytes} bytes"}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
