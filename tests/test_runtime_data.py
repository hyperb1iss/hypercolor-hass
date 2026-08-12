from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from custom_components.hypercolor.api import ServerInfo
from custom_components.hypercolor.runtime_data import (
    ConnectionSource,
    ConnectionState,
    HypercolorRuntimeData,
)
from hypercolor import HypercolorNotFoundError


def test_connection_state_tracks_each_source_and_notifies_listeners() -> None:
    state = ConnectionState()
    notifications = 0

    def listener() -> None:
        nonlocal notifications
        notifications += 1

    remove_listener = state.add_listener(listener)
    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_connected(ConnectionSource.WEBSOCKET)
    state.set_connected(ConnectionSource.WEBSOCKET)
    state.set_disconnected(ConnectionSource.SNAPSHOT, RuntimeError("snapshot down"))
    state.set_disconnected(ConnectionSource.SNAPSHOT, RuntimeError("snapshot down"))

    assert state.connected is True
    assert state.last_connected_at is not None
    assert state.last_disconnected_at is not None
    assert state.last_error == "snapshot down"
    assert notifications == 3
    assert state.snapshot()["sources"]["snapshot"]["connected"] is False

    remove_listener()
    state.set_disconnected(ConnectionSource.WEBSOCKET, RuntimeError("socket down"))
    assert notifications == 3
    assert state.connected is False
    assert state.last_error == "socket down"


def test_connection_grace_and_snapshot_availability_use_source_timestamps() -> None:
    state = ConnectionState()
    assert state.is_connected(grace_s=5) is False
    assert state.is_snapshot_available(unavailable_after_s=5) is False

    state.set_disconnected(ConnectionSource.SNAPSHOT)
    assert state.is_connected(grace_s=5) is False
    assert state.is_source_connected(ConnectionSource.SNAPSHOT, grace_s=5) is False

    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_disconnected(ConnectionSource.SNAPSHOT)

    assert state.is_connected(grace_s=5) is True
    assert state.is_snapshot_available(unavailable_after_s=5) is True

    old = datetime.now(UTC) - timedelta(seconds=10)
    snapshot = state.sources[ConnectionSource.SNAPSHOT]
    snapshot.last_connected_at = old
    snapshot.last_disconnected_at = old

    assert state.is_connected(grace_s=5) is False
    assert state.is_snapshot_available(unavailable_after_s=5) is False

    state.set_connected(ConnectionSource.SNAPSHOT)
    assert state.is_snapshot_available(unavailable_after_s=0) is True


def test_source_connection_does_not_hide_websocket_loss_behind_rest_health() -> None:
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)

    assert state.is_source_connected(ConnectionSource.WEBSOCKET, grace_s=5) is False

    state.set_connected(ConnectionSource.WEBSOCKET)
    state.set_disconnected(ConnectionSource.WEBSOCKET)

    assert state.is_connected() is True
    assert state.is_source_connected(ConnectionSource.WEBSOCKET, grace_s=5) is True

    old = datetime.now(UTC) - timedelta(seconds=10)
    state.sources[ConnectionSource.WEBSOCKET].last_disconnected_at = old
    assert state.is_source_connected(ConnectionSource.WEBSOCKET, grace_s=5) is False


async def test_mutation_gateway_refreshes_successful_results() -> None:
    coordinator = _Coordinator()
    runtime = _runtime(coordinator)

    async def operation() -> str:
        return "applied"

    assert await runtime.async_mutate(operation) == "applied"
    assert coordinator.refreshes == 1


async def test_mutation_gateway_preserves_operation_error_when_refresh_fails() -> None:
    coordinator = _Coordinator(refresh_error=RuntimeError("refresh failed"))
    runtime = _runtime(coordinator)

    async def operation() -> None:
        raise ValueError("mutation failed")

    with pytest.raises(ValueError, match="mutation failed"):
        await runtime.async_mutate(operation)
    assert coordinator.refreshes == 1


@pytest.mark.parametrize(
    ("error", "raises"),
    [
        (None, False),
        (HypercolorNotFoundError("No effect is currently active"), False),
        (HypercolorNotFoundError("Stop endpoint is unavailable"), True),
    ],
)
async def test_stop_effect_normalizes_only_the_idle_response(
    error: Exception | None,
    raises: bool,
) -> None:
    coordinator = _Coordinator()
    client = _StopClient(error)
    runtime = _runtime(coordinator, client=client)

    if raises:
        with pytest.raises(HypercolorNotFoundError, match="Stop endpoint is unavailable"):
            await runtime.async_stop_effect()
    else:
        await runtime.async_stop_effect()

    assert client.stop_calls == 1
    assert coordinator.refreshes == 1


class _Coordinator:
    def __init__(self, *, refresh_error: Exception | None = None) -> None:
        self.data: Any = None
        self.last_update_success = True
        self.refresh_error = refresh_error
        self.refreshes = 0

    async def async_refresh(self) -> None:
        self.refreshes += 1
        if self.refresh_error is not None:
            raise self.refresh_error


class _StopClient:
    def __init__(self, error: Exception | None) -> None:
        self.error = error
        self.stop_calls = 0

    async def stop_effect(self) -> None:
        self.stop_calls += 1
        if self.error is not None:
            raise self.error


def _runtime(coordinator: _Coordinator, *, client: object | None = None) -> HypercolorRuntimeData:
    return HypercolorRuntimeData(
        client=cast(Any, client or object()),
        server=ServerInfo(
            instance_id="srv-1",
            instance_name="Hyperia",
            version="0.3.2",
            auth_required=True,
            device_count=3,
        ),
        coordinator=cast(Any, coordinator),
    )
