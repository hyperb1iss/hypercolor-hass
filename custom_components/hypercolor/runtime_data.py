from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, TypeVar

from hypercolor import HypercolorClient

from .api import ServerInfo
from .models import HypercolorSnapshot

if TYPE_CHECKING:
    from .coordinator import HypercolorCoordinator

ResultT = TypeVar("ResultT")


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

    def set_connected(self, source: ConnectionSource) -> bool:
        state = self.sources[source]
        if state.connected:
            return False
        state.connected = True
        state.last_connected_at = datetime.now(UTC)
        state.last_error = None
        self._notify_listeners()
        return True

    def set_disconnected(
        self,
        source: ConnectionSource,
        error: BaseException | None = None,
    ) -> bool:
        state = self.sources[source]
        error_text = str(error) if error else None
        outage_started = state.connected or state.last_disconnected_at is None
        error_changed = state.last_error != error_text
        if not outage_started and not error_changed:
            return False
        state.connected = False
        if outage_started:
            state.last_disconnected_at = datetime.now(UTC)
        state.last_error = error_text
        self._notify_listeners()
        return True

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
        unavailable_in = self.source_unavailable_in(source, grace_s)
        return unavailable_in is None or unavailable_in > 0

    def source_unavailable_in(
        self,
        source: ConnectionSource,
        grace_s: int,
    ) -> float | None:
        health = self.sources[source]
        if health.connected:
            return None
        if health.last_connected_at is None:
            return 0
        if health.last_disconnected_at is None:
            return 0
        outage_age_s = (datetime.now(UTC) - health.last_disconnected_at).total_seconds()
        return max(grace_s - outage_age_s, 0)

    def is_available(self, unavailable_after_s: int) -> bool:
        unavailable_in = self.unavailable_in(unavailable_after_s)
        return unavailable_in is None or unavailable_in > 0

    def unavailable_in(self, unavailable_after_s: int) -> float | None:
        snapshot = self.sources[ConnectionSource.SNAPSHOT]
        if not snapshot.connected and snapshot.last_connected_at is None:
            return 0
        now = datetime.now(UTC)
        deadlines = [
            max(
                unavailable_after_s - (now - state.last_disconnected_at).total_seconds(),
                0,
            )
            for state in self.sources.values()
            if not state.connected and state.last_disconnected_at is not None
        ]
        return min(deadlines, default=None)

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
        """Empty every renderable zone; the daemon treats an empty scene as a no-op."""
        await self.async_mutate(self.client.clear_scene)


def _latest(values: Iterable[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present, default=None)
