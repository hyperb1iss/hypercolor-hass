from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CHANNELS_AUDIO, CONF_PER_DEVICE_ENTITIES, OPTIONS_DEFAULTS
from .entity import child_device_info, hub_device_info, read_field
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SwitchEntity] = []
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.append(HypercolorAudioReactiveSwitch(entry))
    enabled_devices = set(
        entry.options.get(
            CONF_PER_DEVICE_ENTITIES,
            OPTIONS_DEFAULTS[CONF_PER_DEVICE_ENTITIES],
        )
    )
    devices = entry.runtime_data.coordinators["devices"].data or []
    entities.extend(
        HypercolorDeviceEnabledSwitch(entry, device)
        for device in devices
        if str(read_field(device, "id")) in enabled_devices
    )
    async_add_entities(entities)


class HypercolorAudioReactiveSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Audio reactive"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        self._entry = entry
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_reactive"

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(CONF_CHANNELS_AUDIO, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._entry.runtime_data.client.set_audio_device("default")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._entry.runtime_data.client.set_audio_device("disabled")


class HypercolorDeviceEnabledSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "Enabled"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], device: Any) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["devices"])
        self._entry = entry
        self._device_id = str(read_field(device, "id"))
        self._attr_device_info = child_device_info(runtime, device)
        self._attr_unique_id = f"{runtime.server.instance_id}:device:{self._device_id}:enabled"

    @property
    def is_on(self) -> bool | None:
        if device := self._device:
            return bool(read_field(device, "enabled", True))
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._entry.runtime_data.client.update_device(self._device_id, enabled=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._entry.runtime_data.client.update_device(self._device_id, enabled=False)
        await self.coordinator.async_request_refresh()

    @property
    def _device(self) -> Any | None:
        for device in self.coordinator.data or []:
            if str(read_field(device, "id")) == self._device_id:
                return device
        return None
