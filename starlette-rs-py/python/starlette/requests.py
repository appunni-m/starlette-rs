"""Request values backed by the Rust request parsers and body state."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from starlette_rs_py import _core

from starlette.datastructures import URL, Address, State


async def _empty_receive() -> Any:
    """Match Starlette's unavailable receive callback for detached Requests."""
    raise RuntimeError("Receive channel has not been made available")


class Headers:
    """A small decoded view over Rust-owned ordered raw request headers."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def raw(self) -> list[tuple[bytes, bytes]]:
        return self._inner.raw()

    def get(self, key: str, default: Any = None) -> Any:
        value = self._inner.get(key.encode("latin-1"))
        return default if value is None else value.decode("latin-1")

    def getlist(self, key: str) -> list[str]:
        return [value.decode("latin-1") for value in self._inner.get_list(key.encode("latin-1"))]

    def items(self) -> list[tuple[str, str]]:
        return [(name.decode("latin-1"), value.decode("latin-1")) for name, value in self.raw]

    def __getitem__(self, key: str) -> str:
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __contains__(self, key: str) -> bool:
        return self._inner.get(key.encode("latin-1")) is not None

    def __len__(self) -> int:
        return self._inner.len()


class HTTPConnection(Mapping[str, Any]):
    """Provide the ASGI connection values shared by requests and WebSockets."""

    __slots__ = (
        "scope",
        "_native_headers",
        "_headers",
        "_query_params",
        "_cookies",
        "_url",
        "_base_url",
        "_state",
    )

    def __init__(self, scope: dict[str, Any], receive: Callable[..., Any] | None = None) -> None:
        assert scope["type"] in ("http", "websocket")
        del receive
        self.scope = scope
        self._native_headers = _core.RequestHeaders(scope.get("headers", []))
        self._headers: Headers | None = None
        self._query_params: Any = None
        self._cookies: Any = None
        self._url: URL | None = None
        self._base_url: URL | None = None
        self._state: State | None = None

    def __getitem__(self, key: str) -> Any:
        return self.scope[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.scope)

    def __len__(self) -> int:
        return len(self.scope)

    __eq__ = object.__eq__
    __hash__ = object.__hash__

    @property
    def app(self) -> Any:
        return self.scope["app"]

    @property
    def url(self) -> URL:
        if self._url is None:
            self._url = URL(scope=self.scope)
        return self._url

    @property
    def base_url(self) -> URL:
        if self._base_url is None:
            base_url_scope = dict(self.scope)
            app_root_path = base_url_scope.get("app_root_path", base_url_scope.get("root_path", ""))
            path = app_root_path
            if not path.endswith("/"):
                path += "/"
            base_url_scope["path"] = path
            base_url_scope["query_string"] = b""
            base_url_scope["root_path"] = app_root_path
            self._base_url = URL(scope=base_url_scope)
        return self._base_url

    def url_for(self, name: str, /, **path_params: Any) -> URL:
        url_path_provider = self.scope.get("router") or self.scope.get("app")
        if url_path_provider is None:
            raise RuntimeError(
                "The `url_for` method can only be used inside a Starlette application or with a router."
            )
        url_path = url_path_provider.url_path_for(name, **path_params)
        return url_path.make_absolute_url(base_url=self.base_url)

    @property
    def headers(self) -> Headers:
        if self._headers is None:
            self._headers = Headers(self._native_headers)
        return self._headers

    @property
    def query_params(self) -> Any:
        if self._query_params is None:
            self._query_params = _core.QueryParams(self.scope["query_string"])
        return self._query_params

    @property
    def path_params(self) -> dict[str, Any]:
        return self.scope.get("path_params", {})

    @property
    def cookies(self) -> Any:
        if self._cookies is None:
            self._cookies = _core.Cookies.from_headers(self._native_headers)
        return self._cookies

    @property
    def client(self) -> Address | None:
        host_port = self.scope.get("client")
        return None if host_port is None else Address(*host_port)

    @property
    def state(self) -> State:
        if self._state is None:
            self._state = State(self.scope.setdefault("state", {}))
        return self._state

    @property
    def session(self) -> dict[str, Any]:
        assert "session" in self.scope, (
            "SessionMiddleware must be installed to access request.session"
        )
        return self.scope["session"]

    @property
    def auth(self) -> Any:
        assert "auth" in self.scope, (
            "AuthenticationMiddleware must be installed to access request.auth"
        )
        return self.scope["auth"]

    @property
    def user(self) -> Any:
        assert "user" in self.scope, (
            "AuthenticationMiddleware must be installed to access request.user"
        )
        return self.scope["user"]


class Request(HTTPConnection):
    """Expose ASGI request data without moving receive calls off the host loop."""

    __slots__ = ("_receive", "_body_state", "_body_cache")

    def __init__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__(scope)
        assert scope["type"] == "http"
        self._receive = _empty_receive if receive is None else receive
        self._body_state = _core.RequestBodyAccumulator()
        self._body_cache: bytes | None = None

    @property
    def method(self) -> str:
        return self.scope["method"]

    @property
    def url_path(self) -> str:
        return self.scope["path"]

    @property
    def router(self) -> Any:
        return self.scope["router"]

    async def body(self) -> bytes:
        """Collect and cache request chunks using Rust's body state machine."""
        if self._body_cache is not None:
            return self._body_cache

        self._body_state.begin_body_collection()
        while not self._body_state.is_complete():
            message = await self._receive()
            self._body_state.accept_asgi_message(
                message.get("type", ""),
                message.get("body", b""),
                message.get("more_body", False),
            )
        self._body_cache = self._body_state.cache_body()
        return self._body_cache

    async def json(self) -> Any:
        """Decode the cached request body as JSON on the caller's loop."""
        return json.loads(await self.body())
