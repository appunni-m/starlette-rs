"""Validate request host headers before dispatching to the wrapped app."""

from __future__ import annotations

from collections.abc import Sequence

from starlette_rs_py import _core

from starlette.datastructures import URL
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.responses import Response as Response
from starlette.types import ASGIApp, Receive, Scope, Send

ENFORCE_DOMAIN_WILDCARD = "Domain wildcard patterns must be like '*.example.com'."


class TrustedHostMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        allowed_hosts: Sequence[str] | None = None,
        www_redirect: bool = True,
    ) -> None:
        allowed_hosts = _core._trusted_host_validate(allowed_hosts)
        self.app = app
        self.allowed_hosts = _core._trusted_host_list(allowed_hosts)
        self.allow_any = _core._trusted_host_contains(allowed_hosts)
        self.www_redirect = www_redirect

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await _core._trusted_host_middleware_call(
            self.app,
            self.allowed_hosts,
            self.allow_any,
            self.www_redirect,
            scope,
            receive,
            send,
            _core.HTTPConnection,
            URL,
            RedirectResponse,
            PlainTextResponse,
        )
