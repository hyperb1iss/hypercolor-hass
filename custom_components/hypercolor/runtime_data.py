from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar

from hypercolor import HypercolorClient, HypercolorNotFoundError

from .api import ServerInfo
from .models import HypercolorSnapshot

if TYPE_CHECKING:
    from .coordinator import HypercolorCoordinator

ResultT = TypeVar("ResultT")

_NO_ACTIVE_EFFECT = "No effect is currently active"


class ConnectionSource(StrEnum):
    SNAPSHOT = "snapshot"
    WEBSOCKET = "websocket"


@dataclass(slots=True)
class SourceHealth:
    connected: bool = False
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    last_error: str | None = None


@dataclass(slots=True)
class ConnectionState:
    sources: dict[ConnectionSource, SourceHealth] = field(
        default_factory=lambda: {source: SourceHealth() for source in ConnectionSource}
    )
    _listeners: set[Callable[[], None]] = field(default_factory=set)

    @property
    def connected(self) -> bool:
        return any(source.connected for source in self.sources.values())

    @property
    def last_connected_at(self) -> datetime | None:
        return _latest(source.last_connected_at for source in self.sources.values())

    @property
    def last_disconnected_at(self) -> datetime | None:
        return _latest(source.last_disconnected_at for source in self.sources.values())

    @property
    def last_error(self) -> str | None:
        errors = [
            (source.last_disconnected_at, source.last_error)
            for source in self.sources.values()
            if source.last_error is not None
        ]
        if not errors:
            return None
        return max(errors, key=lambda item: item[0] or datetime.min.replace(tzinfo=UTC))[1]

    def set_connected(self, source: ConnectionSource) -> None:
        state = self.sources[source]
        if state.connected:
            return
        state.connected = True
        state.last_connected_at = datetime.now(UTC)
        state.last_error = None
        self._notify_listeners()

    def set_disconnected(
        self,
        source: ConnectionSource,
        error: BaseException | None = None,
    ) -> None:
        state = self.sources[source]
        error_text = str(error) if error else None
        if (
            not state.connected
            and state.last_disconnected_at is not None
            and state.last_error == error_text
        ):
            return
        state.connected = False
        state.last_disconnected_at = datetime.now(UTC)
        state.last_error = error_text
        self._notify_listeners()

    def is_connected(self, grace_s: int = 0) -> bool:
        if self.connected:
            return True
        if self.last_connected_at is None:
            return False
        disconnected_at = self.last_disconnected_at
        if disconnected_at is None:
            return False
        return (datetime.now(UTC) - disconnected_at).total_seconds() < grace_s

    def is_source_connected(self, source: ConnectionSource, grace_s: int = 0) -> bool:
        health = self.sources[source]
        if health.connected:
            return True
        if health.last_connected_at is None:
            return False
        if health.last_disconnected_at is None:
            return False
        return (datetime.now(UTC) - health.last_disconnected_at).total_seconds() < grace_s

    def is_snapshot_available(self, unavailable_after_s: int) -> bool:
        snapshot = self.sources[ConnectionSource.SNAPSHOT]
        if snapshot.connected:
            return True
        if snapshot.last_connected_at is None:
            return False
        age = datetime.now(UTC) - snapshot.last_connected_at
        return age.total_seconds() < unavailable_after_s

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify_listeners(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def snapshot(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "last_connected_at": self.last_connected_at,
            "last_disconnected_at": self.last_disconnected_at,
            "last_error": self.last_error,
            "sources": {
                source.value: {
                    "connected": state.connected,
                    "last_connected_at": state.last_connected_at,
                    "last_disconnected_at": state.last_disconnected_at,
                    "last_error": state.last_error,
                }
                for source, state in self.sources.items()
            },
        }


@dataclass(slots=True)
class HypercolorRuntimeData:
    client: HypercolorClient
    server: ServerInfo
    coordinator: HypercolorCoordinator
    connection_state: ConnectionState = field(default_factory=ConnectionState)
    per_device_entity_ids: set[str] = field(default_factory=set)
    ws_task: asyncio.Task[None] | None = None
    reconcile_task: asyncio.Task[None] | None = None
    unavailable_task: asyncio.Task[None] | None = None
    refresh_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    @property
    def snapshot(self) -> HypercolorSnapshot:
        return self.coordinator.data

    async def async_mutate(self, operation: Callable[[], Awaitable[ResultT]]) -> ResultT:
        try:
            result = await operation()
        except Exception:
            with contextlib.suppress(Exception):
                await self.coordinator.async_refresh()
            raise
        await self.coordinator.async_refresh()
        return result

    async def async_stop_effect(self) -> None:
        async def stop() -> None:
            try:
                await self.client.stop_effect()
            except HypercolorNotFoundError as exc:
                if str(exc) != _NO_ACTIVE_EFFECT:
                    raise

        await self.async_mutate(stop)


def _latest(values: Iterable[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present, default=None)
