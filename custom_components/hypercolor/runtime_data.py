from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import CALLBACK_TYPE, callback

from .api import ServerInfo


@dataclass(slots=True)
class ConnectionState:
    connected: bool = False
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    last_error: str | None = None
    _listeners: set[Callable[[], None]] = field(default_factory=set)

    def set_connected(self) -> bool:
        changed = not self.connected or self.last_error is not None
        self.connected = True
        if changed:
            self.last_connected_at = datetime.now(UTC)
        self.last_error = None
        if changed:
            self._notify()
        return changed

    def set_disconnected(self, error: BaseException | None = None) -> bool:
        message = str(error) if error else None
        changed = self.connected or self.last_disconnected_at is None
        self.connected = False
        if changed:
            self.last_disconnected_at = datetime.now(UTC)
        self.last_error = message
        if changed:
            self._notify()
        return changed

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.add(listener)

        @callback
        def remove_listener() -> None:
            self._listeners.discard(listener)

        return remove_listener

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "last_connected_at": self.last_connected_at,
            "last_disconnected_at": self.last_disconnected_at,
            "last_error": self.last_error,
        }


@dataclass(slots=True)
class HypercolorRuntimeData:
    client: Any
    server: ServerInfo
    coordinators: dict[str, Any] = field(default_factory=dict)
    connection_state: ConnectionState = field(default_factory=ConnectionState)
    ws_task: asyncio.Task[None] | None = None
    reconcile_task: asyncio.Task[None] | None = None
    unavailable_task: asyncio.Task[None] | None = None
