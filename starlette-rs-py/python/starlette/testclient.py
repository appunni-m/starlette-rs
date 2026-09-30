"""Synchronous TestClient facade over the Rust-owned ASGI transport."""

from __future__ import annotations

from typing import Any

from starlette_rs_py import _core

_httpx = _core.testclient_httpx()


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


class WebSocketTestSession:
    """Synchronous facade over the Rust-owned TestClient WebSocket session."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    @property
    def accepted_subprotocol(self) -> str | None:
        return self._runtime.accepted_subprotocol

    def __enter__(self) -> WebSocketTestSession:
        self._runtime.__enter__()
        return self

    def __exit__(self, *args: Any) -> bool:
        return self._runtime.__exit__(*args)

    def send_text(self, data: str) -> None:
        self._runtime.send_text(data)

    def receive_text(self) -> str:
        return self._runtime.receive_text()

    def send_bytes(self, data: bytes) -> None:
        self._runtime.send_bytes(data)

    def receive_bytes(self) -> bytes:
        return self._runtime.receive_bytes()

    def close(self, code: int = 1000) -> None:
        self._runtime.close(code)


class TestClient(_httpx.Client):
    """Issue synchronous HTTP requests to an ASGI app."""

    __test__ = False

    def __init__(
        self,
        app: Any,
        base_url: str = "http://testserver",
        raise_server_exceptions: bool = True,
        root_path: str = "",
        backend: str = "asyncio",
        backend_options: dict[str, Any] | None = None,
        cookies: Any = None,
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

    def request(
        self,
        method: str,
        url: Any,
        *,
        content: Any = None,
        data: Any = None,
        files: Any = None,
        json: Any = None,
        params: Any = None,
        headers: Any = None,
        cookies: Any = None,
        auth: Any = _httpx.USE_CLIENT_DEFAULT,
        follow_redirects: Any = _httpx.USE_CLIENT_DEFAULT,
        timeout: Any = _httpx.USE_CLIENT_DEFAULT,
        extensions: Any = None,
    ) -> Any:
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

    def websocket_connect(
        self,
        url: str,
        subprotocols: Any = None,
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
