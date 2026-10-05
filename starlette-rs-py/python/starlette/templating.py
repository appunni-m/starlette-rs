"""Jinja2 template integration with Rust-owned Starlette behavior."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from os import PathLike
from typing import Any, overload

from starlette_rs_py import _core

from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse

jinja2 = _core._templating_require_jinja2()
pass_context = _core._templating_context_decorator(jinja2)


class _TemplateResponse(HTMLResponse):
    """Render and send one template response through the Rust runtime."""

    def __init__(
        self,
        template: Any,
        context: dict[str, Any],
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> None:
        self.template = template
        self.context = context
        super().__init__(
            _core._templating_render(template, context),
            status_code,
            headers,
            media_type,
            background,
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await _core._templating_response_call(
            super().__call__, self.template, self.context, scope, receive, send
        )


class Jinja2Templates:
    """Configure Jinja templates and build Starlette-compatible responses."""

    env: jinja2.Environment
    context_processors: list[Callable[[Request], dict[str, Any]]]

    @overload
    def __init__(
        self,
        directory: str | PathLike[str] | Sequence[str | PathLike[str]],
        *,
        context_processors: list[Callable[[Request], dict[str, Any]]] | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        env: jinja2.Environment,
        context_processors: list[Callable[[Request], dict[str, Any]]] | None = None,
    ) -> None: ...

    def __init__(
        self,
        directory: str | PathLike[str] | Sequence[str | PathLike[str]] | None = None,
        *,
        context_processors: list[Callable[[Request], dict[str, Any]]] | None = None,
        env: jinja2.Environment | None = None,
    ) -> None:
        _core._Jinja2Templates.initialize_for(self, (directory, context_processors, env))

    def _setup_env_defaults(self, env: Any) -> None:
        _core._Jinja2Templates.setup_for(env, pass_context)

    def get_template(self, name: str) -> Any:
        return _core._Jinja2Templates.template_for(self, name)

    def TemplateResponse(
        self,
        request: Request,
        name: str,
        context: dict[str, Any] | None = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: BackgroundTask | None = None,
    ) -> _TemplateResponse:
        """Render a template and return an HTML response."""
        return _core._Jinja2Templates.response_for(
            self,
            (
                request,
                name,
                _TemplateResponse,
                context,
                status_code,
                headers,
                media_type,
                background,
            ),
        )
