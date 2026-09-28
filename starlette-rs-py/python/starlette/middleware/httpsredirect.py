"""Redirect cleartext HTTP and WebSocket traffic to secure schemes."""

from starlette_rs_py import _core

from starlette.datastructures import URL
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class HTTPSRedirectMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await _core._https_redirect_middleware_call(
            self.app, scope, receive, send, URL, RedirectResponse
        )
