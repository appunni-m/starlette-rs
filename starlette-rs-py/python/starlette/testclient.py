"""Synchronous TestClient facade over the Rust-owned ASGI transport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, Literal

from starlette_rs_py import _core
from typing_extensions import Self

from starlette.types import ASGIApp, Message, Receive, Send
from starlette.websockets import WebSocketDisconnect

ASGIInstance = Callable[[Receive, Send], Awaitable[None]]
_RequestData = Mapping[str, str | Iterable[str] | bytes]

httpx = _core.testclient_httpx()
_httpx = httpx


async def _run_asgi3(app: Any, scope: Any, receive: Any, send: Any) -> None:
    await app(scope, receive, send)


async def _run_asgi2(app: Any, scope: Any, receive: Any, send: Any) -> None:
    await app(scope)(receive, send)


class _TestClientTransport(_httpx.BaseTransport):
    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def handle_request(self, request: Any) -> Any:
        return self._runtime.handle_request(request)

    def close(self) -> None:
        self._runtime.close()


class WebSocketDenialResponse(  # type: ignore[misc]
    _httpx.Response,
    WebSocketDisconnect,
):
    """Response raised when a WebSocket handshake is denied with an HTTP response."""


class WebSocketTestSession:
    """Synchronous facade over the Rust-owned TestClient WebSocket session."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    @property
    def accepted_subprotocol(self) -> str | None:
        return self._runtime.accepted_subprotocol

    @property
    def extra_headers(self) -> Any:
        return self._runtime.extra_headers

    def __enter__(self) -> Self:
        self._runtime.__enter__()
        return self

    def __exit__(self, *args: Any) -> bool | None:
        return self._runtime.__exit__(*args)

    def send(self, message: Message) -> None:
        self._runtime.send(message)

    def receive(self) -> Message:
        return self._runtime.receive()

    def send_text(self, data: str) -> None:
        self._runtime.send_text(data)

    def receive_text(self) -> str:
        return self._runtime.receive_text()

    def send_bytes(self, data: bytes) -> None:
        self._runtime.send_bytes(data)

    def receive_bytes(self) -> bytes:
        return self._runtime.receive_bytes()

    def send_json(self, data: Any, mode: Literal["text", "binary"] = "text") -> None:
        self._runtime.send_json(data, mode)

    def receive_json(self, mode: Literal["text", "binary"] = "text") -> Any:
        return self._runtime.receive_json(mode)

    def close(self, code: int = 1000, reason: str | None = None) -> None:
        self._runtime.close(code, reason)


class TestClient(_httpx.Client):
    """Issue synchronous HTTP requests to an ASGI app."""

    __test__ = False

    def __init__(
        self,
        app: ASGIApp,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        backend: Literal["asyncio", "trio"] = "asyncio",
        backend_options: dict[str, Any] | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        client: tuple[str, int] = ("testclient", 50000),
    ) -> None:
        self._testclient_runtime = _core.TestClientTransport(
            app,
            _httpx,
            (_run_asgi3, _run_asgi2),
            {
                "backend": backend,
                "backend_options": backend_options,
                "raise_server_exceptions": raise_server_exceptions,
                "root_path": root_path,
                "client": client,
            },
        )
        self.app = app
        self.app_state = self._testclient_runtime.app_state
        self.async_backend = self._testclient_runtime.async_backend
        transport = _TestClientTransport(self._testclient_runtime)
        headers = self._testclient_runtime.default_headers(headers)
        super().__init__(
            base_url=base_url,
            headers=headers,
            transport=transport,
            follow_redirects=follow_redirects,
            cookies=cookies,
        )

    def __enter__(self) -> Self:
        return self._testclient_runtime.__enter__(self)

    def __exit__(self, *args: Any) -> None:
        return self._testclient_runtime.__exit__(self, *args)

    async def lifespan(self) -> None:
        await self._testclient_runtime.lifespan()

    async def wait_startup(self) -> None:
        await self._testclient_runtime.wait_startup()

    async def wait_shutdown(self) -> None:
        await self._testclient_runtime.wait_shutdown()

    def request(
        self,
        method: str,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes
        | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return self._testclient_runtime.request(
            self,
            method,
            url,
            {
                "content": content,
                "data": data,
                "files": files,
                "json": json,
                "params": params,
                "headers": headers,
                "cookies": cookies,
                "auth": auth,
                "follow_redirects": follow_redirects,
                "timeout": timeout,
                "extensions": extensions,
            },
        )

    def get(
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def options(
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().options(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def head(
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().head(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def post(
        self,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().post(
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def put(
        self,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().put(
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def patch(
        self,
        url: httpx._types.URLTypes,
        *,
        content: httpx._types.RequestContent | None = None,
        data: _RequestData | None = None,
        files: httpx._types.RequestFiles | None = None,
        json: Any = None,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().patch(
            url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def delete(
        self,
        url: httpx._types.URLTypes,
        *,
        params: httpx._types.QueryParamTypes | None = None,
        headers: httpx._types.HeaderTypes | None = None,
        cookies: httpx._types.CookieTypes | None = None,
        auth: httpx._types.AuthTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: bool | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        timeout: httpx._types.TimeoutTypes | httpx._client.UseClientDefault = _httpx.USE_CLIENT_DEFAULT,
        extensions: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return super().delete(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            auth=auth,
            follow_redirects=follow_redirects,
            timeout=timeout,
            extensions=extensions,
        )

    def websocket_connect(
        self,
        url: str,
        subprotocols: Sequence[str] | None = None,
        **kwargs: Any,
    ) -> WebSocketTestSession:
        return WebSocketTestSession(
            self._testclient_runtime.websocket_connect(
                self,
                url,
                subprotocols,
                kwargs,
            )
        )
