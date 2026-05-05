from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .api import ServerInfo


@dataclass(slots=True)
class ConnectionState:
    connected: bool = False
    last_connected_at: datetime | None = None
    last_disconnected_at: datetime | None = None
    last_error: str | None = None

    def set_connected(self) -> None:
        self.connected = True
        self.last_connected_at = datetime.now(UTC)
        self.last_error = None

    def set_disconnected(self, error: BaseException | None = None) -> None:
        self.connected = False
        self.last_disconnected_at = datetime.now(UTC)
        self.last_error = str(error) if error else None

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
    per_device_entity_ids: set[str] = field(default_factory=set)
    ws_task: asyncio.Task[None] | None = None
    reconcile_task: asyncio.Task[None] | None = None
