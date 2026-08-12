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
    _availability_timer: CALLBACK_TYPE | None = None

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        self._entry = entry
        self._runtime = entry.runtime_data
        super().__init__(self._runtime.coordinator)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_availability_timer)
        self.async_on_remove(
            self._runtime.connection_state.add_listener(self._availability_updated)
        )
        self._availability_updated()

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
        return self._runtime.connection_state.is_available(unavailable_after_s)

    @callback
    def _availability_updated(self) -> None:
        self._cancel_availability_timer()
        unavailable_after_s = int(
            self._entry.options.get(
                CONF_UNAVAILABLE_AFTER_S,
                OPTIONS_DEFAULTS[CONF_UNAVAILABLE_AFTER_S],
            )
        )
        unavailable_in = self._runtime.connection_state.unavailable_in(unavailable_after_s)
        if unavailable_in is not None and unavailable_in > 0:
            self._availability_timer = async_call_later(
                self.hass,
                unavailable_in,
                self._availability_expired,
            )
        self.async_write_ha_state()

    @callback
    def _availability_expired(self, *_: object) -> None:
        self._availability_timer = None
        self.async_write_ha_state()

    @callback
    def _cancel_availability_timer(self) -> None:
        if self._availability_timer is not None:
            self._availability_timer()
            self._availability_timer = None


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
        unavailable_in = self._runtime.connection_state.source_unavailable_in(
            ConnectionSource.WEBSOCKET,
            grace_s,
        )
        if unavailable_in is not None and unavailable_in > 0:
            self._connection_timer = async_call_later(
                self.hass,
                unavailable_in,
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


class HypercolorDeviceEntity(HypercolorEntity):
    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        device: Device,
    ) -> None:
        super().__init__(entry)
        self._device_id = device.id
        self._attr_device_info = child_device_info(self._runtime, device)

    @property
    def available(self) -> bool:
        return super().available and self._device is not None

    @property
    def _device(self) -> Device | None:
        return self.snapshot.device(self._device_id)


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
