"""Validate request host headers before dispatching to the wrapped app."""

from __future__ import annotations

from collections.abc import Sequence

from starlette_rs_py import _core

from starlette.datastructures import URL
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.responses import Response as Response
from starlette.types import ASGIApp, Receive, Scope, Send

ENFORCE_DOMAIN_WILDCARD = _core.ENFORCE_DOMAIN_WILDCARD


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
            {
                "app": self.app,
                "allowed_hosts": self.allowed_hosts,
                "allow_any": self.allow_any,
                "www_redirect": self.www_redirect,
                "scope": scope,
                "receive": receive,
                "send": send,
                "connection_type": _core.HTTPConnection,
                "url_type": URL,
                "redirect_response_type": RedirectResponse,
                "plain_text_response_type": PlainTextResponse,
            }
        )
