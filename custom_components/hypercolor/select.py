from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CHANNELS_AUDIO
from .entity import catalog_items, hub_device_info, item_id, item_name, option_map, read_field
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SelectEntity] = [
        HypercolorCatalogSelect(
            entry,
            key="scenes",
            name="Scene",
            unique_suffix="scene",
            active_key="active_scene",
            action=entry.runtime_data.client.activate_scene,
        ),
        HypercolorCatalogSelect(
            entry,
            key="profiles",
            name="Profile",
            unique_suffix="profile",
            active_key=None,
            action=entry.runtime_data.client.apply_profile,
        ),
        HypercolorCatalogSelect(
            entry,
            key="layouts",
            name="Layout",
            unique_suffix="layout",
            active_key="active_layout",
            action=entry.runtime_data.client.apply_layout,
        ),
        HypercolorCatalogSelect(
            entry,
            key="presets",
            name="Preset",
            unique_suffix="preset",
            active_key="active_preset",
            action=entry.runtime_data.client.apply_preset,
        ),
    ]
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.append(HypercolorAudioDeviceSelect(entry))
    async_add_entities(entities)


class HypercolorCatalogSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        *,
        key: str,
        name: str,
        unique_suffix: str,
        active_key: str | None,
        action: Callable[[str], Awaitable[Any]],
    ) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["catalog"])
        self._entry = entry
        self._state = runtime.coordinators["state"]
        self._key = key
        self._active_key = active_key
        self._action = action
        self._attr_name = name
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:{unique_suffix}"

    @property
    def options(self) -> list[str]:
        items = self._items
        if self._key != "presets":
            return [item_name(item) for item in items]
        active_effect = read_field(self._state.data, "active_effect_id")
        return [
            item_name(item)
            for item in items
            if read_field(item, "effect_id", active_effect) == active_effect
        ]

    @property
    def current_option(self) -> str | None:
        if self._active_key is None:
            return None
        if self._active_key == "active_preset":
            active = read_field(self._state.data, "active_effect_detail")
            active_id = read_field(active, "active_preset_id")
        else:
            active_id = read_field(self._state.data, self._active_key)
        if not active_id:
            return None
        for item in self._items:
            if item_id(item) == str(active_id):
                return item_name(item)
        return None

    async def async_select_option(self, option: str) -> None:
        mapping = option_map(self._items)
        await self._action(mapping.get(option, option))
        await self._state.async_request_refresh()
        await self.coordinator.async_request_refresh()

    @property
    def _items(self) -> list[Any]:
        return catalog_items(self.coordinator.data, self._key)


class HypercolorAudioDeviceSelect(CoordinatorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Audio device"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["audio"])
        self._entry = entry
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_device"

    @property
    def options(self) -> list[str]:
        return [item_name(device) for device in self._devices]

    @property
    def current_option(self) -> str | None:
        current = read_field(read_field(self.coordinator.data, "devices"), "current")
        for device in self._devices:
            if item_id(device) == current:
                return item_name(device)
        return None

    async def async_select_option(self, option: str) -> None:
        mapping = option_map(self._devices)
        await self._entry.runtime_data.client.set_audio_device(mapping.get(option, option))
        await self.coordinator.async_request_refresh()

    @property
    def _devices(self) -> list[Any]:
        devices = read_field(read_field(self.coordinator.data, "devices"), "devices", [])
        return list(devices) if isinstance(devices, list) else []
