from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.util import slugify

from hypercolor.models import Device

from .const import (
    CONF_DISCONNECT_GRACE_S,
    CONF_UNAVAILABLE_AFTER_S,
    DEFAULT_DISCONNECT_GRACE_S,
    DOMAIN,
    OPTIONS_DEFAULTS,
)
from .models import HypercolorSnapshot
from .runtime_data import ConnectionSource, HypercolorRuntimeData


class DeviceEntityFactory(Protocol):
    def __call__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        device: Device,
    ) -> Any: ...


class HypercolorEntity(CoordinatorEntity[DataUpdateCoordinator[HypercolorSnapshot]]):
    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        self._entry = entry
        self._runtime = entry.runtime_data
        super().__init__(self._runtime.coordinator)

    @property
    def snapshot(self) -> HypercolorSnapshot:
        return self._runtime.snapshot

    @property
    def available(self) -> bool:
        unavailable_after_s = int(
            self._entry.options.get(
                CONF_UNAVAILABLE_AFTER_S,
                OPTIONS_DEFAULTS[CONF_UNAVAILABLE_AFTER_S],
            )
        )
        return super().available and self._runtime.connection_state.is_snapshot_available(
            unavailable_after_s
        )


class HypercolorWebsocketEntity(HypercolorEntity):
    _connection_timer: CALLBACK_TYPE | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_connection_timer)
        self.async_on_remove(self._runtime.connection_state.add_listener(self._connection_updated))
        self._connection_updated()

    @callback
    def _connection_updated(self) -> None:
        self._cancel_connection_timer()
        grace_s = int(
            self._entry.options.get(
                CONF_DISCONNECT_GRACE_S,
                DEFAULT_DISCONNECT_GRACE_S,
            )
        )
        if (
            grace_s > 0
            and not self._runtime.connection_state.sources[ConnectionSource.WEBSOCKET].connected
        ):
            self._connection_timer = async_call_later(
                self.hass,
                grace_s,
                self._connection_grace_expired,
            )
        self.async_write_ha_state()

    @callback
    def _connection_grace_expired(self, *_: object) -> None:
        self._connection_timer = None
        self.async_write_ha_state()

    @callback
    def _cancel_connection_timer(self) -> None:
        if self._connection_timer is not None:
            self._connection_timer()
            self._connection_timer = None

    @property
    def available(self) -> bool:
        grace_s = int(
            self._entry.options.get(
                CONF_DISCONNECT_GRACE_S,
                DEFAULT_DISCONNECT_GRACE_S,
            )
        )
        return super().available and self._runtime.connection_state.is_source_connected(
            ConnectionSource.WEBSOCKET,
            grace_s,
        )


def add_configured_device_entities(
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
    factory: DeviceEntityFactory,
) -> None:
    runtime = entry.runtime_data
    known_ids: set[str] = set()

    @callback
    def sync_entities() -> None:
        configured_ids = set(entry.options.get("per_device_entities", []))
        fresh = [
            device
            for device in runtime.snapshot.devices
            if device.id in configured_ids and device.id not in known_ids
        ]
        if not fresh:
            return
        known_ids.update(device.id for device in fresh)
        async_add_entities([factory(entry, device) for device in fresh])

    sync_entities()
    entry.async_on_unload(runtime.coordinator.async_add_listener(sync_entities))


def hub_device_info(runtime: HypercolorRuntimeData, entry_data: Mapping[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, runtime.server.instance_id)},
        name=runtime.server.instance_name,
        manufacturer="Hypercolor",
        model="Daemon",
        sw_version=runtime.server.version,
        configuration_url=f"http://{entry_data['host']}:{entry_data['port']}",
    )


def child_device_info(runtime: HypercolorRuntimeData, device: Device) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, child_device_identifier(runtime, device.id))},
        name=device.name,
        manufacturer="Hypercolor",
        model=device.backend,
        sw_version=device.firmware_version,
        via_device=(DOMAIN, runtime.server.instance_id),
    )


def child_device_identifier(runtime: HypercolorRuntimeData, device_id: str) -> str:
    return f"{runtime.server.instance_id}:device:{device_id}"


def device_slug(device_id: str) -> str:
    return slugify(device_id).replace("__", "_")
