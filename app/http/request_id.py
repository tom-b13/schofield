"""Request ID middleware.

Assigns a stable X-Request-Id header to each request when absent.
"""

from __future__ import annotations

import uuid
from typing import Callable


class RequestIdMiddleware:
    def __init__(self, app, header_name: str = "X-Request-Id") -> None:  # type: ignore[no-untyped-def]
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        generated = str(uuid.uuid4())
        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                header_bytes = self.header_name.encode("latin-1")
                lower = [k.lower() if isinstance(k, (bytes, bytearray)) else str(k).lower() for k, _ in headers]
                if header_bytes not in lower and self.header_name.lower() not in lower:
                    headers.append((header_bytes, generated.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


__all__ = ["RequestIdMiddleware"]

