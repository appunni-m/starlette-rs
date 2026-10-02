"""Request compatibility facades backed by Rust-owned connection state."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from typing import Any, Generic

from starlette_rs_py import _core
from typing_extensions import TypeVar

from starlette.datastructures import URL, Address, Headers, QueryParams, State

StateT = TypeVar("StateT", bound=Mapping[str, Any] | State, default=State)


class ClientDisconnect(Exception):
    """The client disconnected while the request body was being read."""


async def empty_receive() -> Any:
    """Return the same missing-receive failure as the upstream callback."""
    return await _core._empty_receive()


async def empty_send(message: Any) -> Any:
    """Return the same missing-send failure as the upstream callback."""
    return await _core._empty_send()


class HTTPConnection(Mapping[str, Any], Generic[StateT]):
    """Provide the ASGI connection values shared by requests and WebSockets."""

    __slots__ = ("_inner",)

    def __init__(self, scope: dict[str, Any], receive: Callable[..., Any] | None = None) -> None:
        self._inner = _core.HTTPConnection(scope)

    @property
    def scope(self) -> dict[str, Any]:
        return self._inner.scope

    @scope.setter
    def scope(self, value: dict[str, Any]) -> None:
        self._inner.scope = value

    def __getitem__(self, key: str) -> Any:
        return self._inner[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._inner)

    def __len__(self) -> int:
        return len(self._inner)

    __eq__ = object.__eq__
    __hash__ = object.__hash__

    @property
    def app(self) -> Any:
        return self._inner.app

    @property
    def url(self) -> URL:
        return self._inner.url

    @property
    def base_url(self) -> URL:
        return self._inner.base_url

    def url_for(self, name: str, /, **path_params: Any) -> URL:
        return self._inner.url_for(name, **path_params)

    @property
    def headers(self) -> Headers:
        return self._inner.headers

    @property
    def query_params(self) -> QueryParams:
        return self._inner.query_params

    @property
    def path_params(self) -> dict[str, Any]:
        return self._inner.path_params

    @property
    def cookies(self) -> Any:
        return self._inner.cookies

    @property
    def client(self) -> Address | None:
        return self._inner.client

    @property
    def state(self) -> StateT:
        return self._inner.state

    @property
    def session(self) -> dict[str, Any]:
        return self._inner.session

    @property
    def auth(self) -> Any:
        return self._inner.auth

    @property
    def user(self) -> Any:
        return self._inner.user


class Request(HTTPConnection[StateT]):
    """Expose ASGI request data without moving receive calls off the host loop."""

    __slots__ = ("_body_state", "_send")

    def __init__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Any] = empty_receive,
        send: Callable[..., Any] = empty_send,
    ) -> None:
        self._inner = _core.HTTPConnection(scope, "http")
        self._body_state = _core.RequestBody(receive)
        self._send = send

    @property
    def method(self) -> str:
        return self._inner.method

    @property
    def url_path(self) -> str:
        return self._inner.url_path

    @property
    def router(self) -> Any:
        return self._inner.router

    @property
    def receive(self) -> Callable[..., Any]:
        return self._body_state.receive

    def stream(self) -> AsyncIterator[bytes]:
        """Return the Rust-owned ASGI request stream iterator."""
        return self._body_state.stream()

    async def body(self) -> bytes:
        """Collect and cache request chunks using Rust's body state machine."""
        return await self._body_state.body()

    async def json(self) -> Any:
        """Decode and cache JSON using Rust-owned request state."""
        return await self._body_state.json()

    def form(
        self,
        *,
        max_files: int | float = 1000,
        max_fields: int | float = 1000,
        max_part_size: int = 1024 * 1024,
    ) -> Any:
        """Return an awaitable context manager for parsed form data."""
        return self._body_state.form(
            self.headers.get("Content-Type"),
            self.scope,
            max_files,
            max_fields,
            max_part_size,
        )

    async def close(self) -> None:
        await self._body_state.close_form()

    async def is_disconnected(self) -> bool:
        return await self._body_state.is_disconnected()

    async def send_push_promise(self, path: str) -> None:
        await self._inner._send_push_promise(self._send, path)
