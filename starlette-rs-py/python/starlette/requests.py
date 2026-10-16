"""Request compatibility facades backed by Rust-owned connection state."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator, Mapping
from typing import Any, Generic, NoReturn

from starlette_rs_py import _core
from typing_extensions import TypeVar

from starlette._utils import AwaitableOrContextManager
from starlette.datastructures import URL, Address, FormData, Headers, QueryParams, State
from starlette.formparsers import MultiPartException as MultiPartException
from starlette.types import Message, Receive, Scope, Send

parse_options_header = _core._request_form_dependency()

StateT = TypeVar("StateT", bound=Mapping[str, Any] | State, default=State)


class ClientDisconnect(Exception):
    """The client disconnected while the request body was being read."""


async def empty_receive() -> NoReturn:
    """Return the same missing-receive failure as the upstream callback."""
    return await _core._empty_receive()


async def empty_send(message: Message) -> NoReturn:
    """Return the same missing-send failure as the upstream callback."""
    return await _core._empty_send()


class HTTPConnection(Mapping[str, Any], Generic[StateT]):
    """Provide the ASGI connection values shared by requests and WebSockets."""

    __slots__ = ("_inner",)

    def __init__(self, scope: Scope, receive: Receive | None = None) -> None:
        self._inner = _core.HTTPConnection(scope, debug=__debug__)
        self.scope = scope

    @property
    def scope(self) -> Scope:
        return self._inner.scope

    @scope.setter
    def scope(self, value: Scope) -> None:
        self._inner.scope = value

    def __getitem__(self, key: str) -> Any:
        return _core.HTTPConnection._getitem_value(self, key)

    def __iter__(self) -> Iterator[str]:
        return _core.HTTPConnection._iter_value(self)

    def __len__(self) -> int:
        return _core.HTTPConnection._len_value(self)

    __eq__ = object.__eq__
    __hash__ = object.__hash__

    @property
    def app(self) -> Any:
        return _core.HTTPConnection._app_value(self)

    @property
    def url(self) -> URL:
        return _core.HTTPConnection._url_value(self._inner, self)

    @property
    def base_url(self) -> URL:
        return _core.HTTPConnection._base_url_value(self._inner, self)

    def url_for(self, name: str, /, **path_params: Any) -> URL:
        return _core.HTTPConnection._url_for(self._inner, self, name, **path_params)

    @property
    def headers(self) -> Headers:
        return _core.HTTPConnection._headers_value(self._inner, self)

    @property
    def query_params(self) -> QueryParams:
        return _core.HTTPConnection._query_params_value(self._inner, self)

    @property
    def path_params(self) -> dict[str, Any]:
        return _core.HTTPConnection._path_params_value(self)

    @property
    def cookies(self) -> dict[str, str]:
        return _core.HTTPConnection._cookies_for(self._inner, self)

    @property
    def client(self) -> Address | None:
        return _core.HTTPConnection._client_value(self)

    @property
    def state(self) -> StateT:
        return _core.HTTPConnection._state_value(self._inner, self)

    @property
    def session(self) -> dict[str, Any]:
        return _core.HTTPConnection._session_value(self, __debug__)

    @property
    def auth(self) -> Any:
        return _core.HTTPConnection._auth_value(self, __debug__)

    @property
    def user(self) -> Any:
        return _core.HTTPConnection._user_value(self, __debug__)


class Request(HTTPConnection[StateT]):
    """Expose ASGI request data without moving receive calls off the host loop."""

    __slots__ = ("_body_state", "_send")

    def __init__(
        self,
        scope: Scope,
        receive: Receive = empty_receive,
        send: Send = empty_send,
    ):
        self._inner = _core.HTTPConnection(scope, debug=__debug__)
        self.scope = scope
        _core.HTTPConnection._assert_scope_type(scope, "http", __debug__)
        self._body_state = _core.RequestBody(receive)
        self._send = send

    @property
    def method(self) -> str:
        return _core.HTTPConnection._method_value(self)

    @property
    def url_path(self) -> str:
        return _core.HTTPConnection._url_path_value(self)

    @property
    def router(self) -> Any:
        return _core.HTTPConnection._router_value(self)

    @property
    def receive(self) -> Receive:
        return self._body_state.receive

    @property
    def _receive(self) -> Receive:
        return self._body_state.receive

    @_receive.setter
    def _receive(self, receive: Receive) -> None:
        self._body_state.set_receive(receive)

    def stream(self) -> AsyncGenerator[bytes, None]:
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
    ) -> AwaitableOrContextManager[FormData]:
        """Return an awaitable context manager for parsed form data."""
        return self._body_state.form(
            self,
            max_files,
            max_fields,
            max_part_size,
        )

    async def close(self) -> None:
        await self._body_state.close_form()

    async def is_disconnected(self) -> bool:
        return await self._body_state.is_disconnected()

    async def send_push_promise(self, path: str) -> None:
        await _core.HTTPConnection._send_push_promise(self, self._send, path)
