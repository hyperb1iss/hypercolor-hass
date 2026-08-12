from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from custom_components.hypercolor import (
    binary_sensor as binary_sensor_module,
    entity as entity_module,
)
from custom_components.hypercolor.binary_sensor import HypercolorConnectedBinarySensor
from custom_components.hypercolor.entity import (
    HypercolorEntity,
    HypercolorWebsocketEntity,
    add_configured_device_entities,
)
from custom_components.hypercolor.runtime_data import ConnectionSource, ConnectionState


def test_entity_availability_honors_source_outage_deadlines(monkeypatch) -> None:
    scheduled: list[tuple[float, Any]] = []

    def schedule(_hass: Any, delay: float, callback: Any) -> Any:
        scheduled.append((delay, callback))
        return lambda: None

    monkeypatch.setattr(entity_module, "async_call_later", schedule)
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    state.sources[ConnectionSource.SNAPSHOT].last_connected_at = datetime.now(UTC) - timedelta(
        minutes=10
    )
    state.set_disconnected(ConnectionSource.SNAPSHOT, ConnectionError("offline"))
    coordinator = SimpleNamespace(last_update_success=False)
    entry: Any = SimpleNamespace(
        options={"unavailable_after_s": 30},
        runtime_data=SimpleNamespace(
            coordinator=coordinator,
            connection_state=state,
        ),
    )
    entity = _TestEntity(entry)
    entity.hass = cast(Any, SimpleNamespace())

    entity._availability_updated()

    assert entity.available is True
    assert 29 < scheduled[0][0] <= 30

    state.sources[ConnectionSource.SNAPSHOT].last_disconnected_at = datetime.now(UTC) - timedelta(
        seconds=31
    )
    scheduled[0][1]()

    assert entity.available is False
    assert entity.writes == 2

    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_connected(ConnectionSource.WEBSOCKET)
    state.set_disconnected(ConnectionSource.WEBSOCKET, ConnectionError("socket offline"))
    entity._availability_updated()

    assert entity.available is True
    assert 29 < scheduled[-1][0] <= 30

    state.sources[ConnectionSource.WEBSOCKET].last_disconnected_at = datetime.now(UTC) - timedelta(
        seconds=31
    )
    scheduled[-1][1]()

    assert entity.available is False
    assert entity.writes == 4


def test_websocket_entity_reschedules_against_original_outage(monkeypatch) -> None:
    scheduled: list[tuple[float, Any]] = []

    def schedule(_hass: Any, delay: float, callback: Any) -> Any:
        scheduled.append((delay, callback))
        return lambda: None

    monkeypatch.setattr(entity_module, "async_call_later", schedule)
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_connected(ConnectionSource.WEBSOCKET)
    state.set_disconnected(ConnectionSource.WEBSOCKET, ConnectionError("offline"))
    entry: Any = SimpleNamespace(
        options={"disconnect_grace_s": 5, "unavailable_after_s": 30},
        runtime_data=SimpleNamespace(
            coordinator=SimpleNamespace(last_update_success=True),
            connection_state=state,
        ),
    )
    entity = _TestWebsocketEntity(entry)
    entity.hass = cast(Any, SimpleNamespace())

    entity._connection_updated()

    assert entity.available is True
    assert 4 < scheduled[-1][0] <= 5

    websocket = state.sources[ConnectionSource.WEBSOCKET]
    websocket.last_disconnected_at = datetime.now(UTC) - timedelta(seconds=3)
    state.set_disconnected(ConnectionSource.WEBSOCKET, ConnectionError("still offline"))
    entity._connection_updated()

    assert 1 < scheduled[-1][0] <= 2

    websocket.last_disconnected_at = datetime.now(UTC) - timedelta(seconds=6)
    scheduled[-1][1]()

    assert entity.available is False
    assert entity.writes == 3


def test_connectivity_sensor_reschedules_against_original_outage(monkeypatch) -> None:
    scheduled: list[tuple[float, Any]] = []

    def schedule(_hass: Any, delay: float, callback: Any) -> Any:
        scheduled.append((delay, callback))
        return lambda: None

    monkeypatch.setattr(binary_sensor_module, "async_call_later", schedule)
    state = ConnectionState()
    state.set_connected(ConnectionSource.WEBSOCKET)
    state.set_disconnected(ConnectionSource.WEBSOCKET, ConnectionError("offline"))
    entry: Any = SimpleNamespace(
        data={"host": "127.0.0.1", "port": 9420},
        options={"disconnect_grace_s": 5},
        runtime_data=SimpleNamespace(
            connection_state=state,
            server=SimpleNamespace(
                instance_id="instance-1",
                instance_name="Test Hypercolor",
                version="0.3.2",
            ),
        ),
    )
    entity = HypercolorConnectedBinarySensor(entry)
    entity.hass = cast(Any, SimpleNamespace())
    entity.async_write_ha_state = cast(Any, lambda: None)

    entity._connection_updated()

    assert entity.is_on is True
    assert 4 < scheduled[-1][0] <= 5

    websocket = state.sources[ConnectionSource.WEBSOCKET]
    websocket.last_disconnected_at = datetime.now(UTC) - timedelta(seconds=3)
    state.set_disconnected(ConnectionSource.WEBSOCKET, ConnectionError("still offline"))
    entity._connection_updated()

    assert 1 < scheduled[-1][0] <= 2

    websocket.last_disconnected_at = datetime.now(UTC) - timedelta(seconds=6)
    scheduled[-1][1]()

    assert entity.is_on is False


def test_configured_device_entities_follow_live_discovery() -> None:
    coordinator = _Coordinator()
    devices = [SimpleNamespace(id="wled-office")]
    entry: Any = SimpleNamespace(
        options={"per_device_entities": ["wled-office", "corsair-lcd"]},
        runtime_data=SimpleNamespace(
            coordinator=coordinator,
            snapshot=SimpleNamespace(devices=devices),
        ),
        async_on_unload=lambda remove: None,
    )
    added: list[str] = []

    def add_entities(entities: list[Any]) -> None:
        added.extend(str(entity) for entity in entities)

    add_configured_device_entities(
        entry,
        cast(Any, add_entities),
        cast(Any, lambda _entry, device: str(device.id)),
    )
    devices.append(SimpleNamespace(id="corsair-lcd"))
    coordinator.listener()
    coordinator.listener()

    assert added == ["wled-office", "corsair-lcd"]


class _Coordinator:
    def __init__(self) -> None:
        self.listener = lambda: None

    def async_add_listener(self, listener: Any) -> Any:
        self.listener = listener
        return lambda: None


class _TestEntity(HypercolorEntity):
    def __init__(self, entry: Any) -> None:
        super().__init__(entry)
        self.writes = 0

    def async_write_ha_state(self) -> None:
        self.writes += 1


class _TestWebsocketEntity(HypercolorWebsocketEntity):
    def __init__(self, entry: Any) -> None:
        super().__init__(entry)
        self.writes = 0

    def async_write_ha_state(self) -> None:
        self.writes += 1
