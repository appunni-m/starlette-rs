"""Input-defined WebSocket JSON mode values for live parity adapters."""

from __future__ import annotations

from typing import Any


def materialize_websocket_json_mode(value: Any) -> Any:
    """Build the stateful string mode used by the comparison-order input."""
    if not isinstance(value, dict) or value.get("kind") != (
        "websocket-mode-equality-after-membership"
    ):
        return value

    mode_value = value["value"]
    error_message = value["message"]

    class InputWebSocketJsonMode(str):
        def __new__(cls) -> InputWebSocketJsonMode:
            instance = super().__new__(cls, mode_value)
            instance.comparisons = 0
            return instance

        def __eq__(self, other: object) -> bool:
            if other == mode_value:
                self.comparisons += 1
                if self.comparisons == 2:
                    raise ValueError(error_message)
                return True
            return super().__eq__(other)

        __hash__ = str.__hash__

    return InputWebSocketJsonMode()
