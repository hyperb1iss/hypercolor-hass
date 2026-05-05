from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PER_DEVICE_ENTITIES, OPTIONS_DEFAULTS
from .entity import catalog_items, child_device_info, hub_device_info, item_id, read_field
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[ButtonEntity] = [
        HypercolorActionButton(
            entry,
            name="Discover devices",
            unique_suffix="discover_devices",
            action=entry.runtime_data.client.discover_devices,
        ),
        HypercolorEffectNavigationButton(entry, "Previous effect", "previous_effect", -1),
        HypercolorEffectNavigationButton(entry, "Next effect", "next_effect", 1),
        HypercolorEffectNavigationButton(entry, "Random effect", "random_effect", 0),
        HypercolorActionButton(
            entry,
            name="Stop effect",
            unique_suffix="stop_effect",
            action=entry.runtime_data.client.stop_effect,
        ),
    ]
    enabled_devices = set(
        entry.options.get(
            CONF_PER_DEVICE_ENTITIES,
            OPTIONS_DEFAULTS[CONF_PER_DEVICE_ENTITIES],
        )
    )
    devices = entry.runtime_data.coordinators["devices"].data or []
    entities.extend(
        HypercolorIdentifyDeviceButton(entry, device)
        for device in devices
        if str(read_field(device, "id")) in enabled_devices
    )
    async_add_entities(entities)


class HypercolorActionButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        *,
        name: str,
        unique_suffix: str,
        action: Callable[[], Awaitable[Any]],
    ) -> None:
        runtime = entry.runtime_data
        self._entry = entry
        self._action = action
        self._attr_name = name
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:{unique_suffix}"

    async def async_press(self) -> None:
        await self._action()
        await self._entry.runtime_data.coordinators["state"].async_request_refresh()


class HypercolorEffectNavigationButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        name: str,
        unique_suffix: str,
        step: int,
    ) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["catalog"])
        self._entry = entry
        self._state = runtime.coordinators["state"]
        self._step = step
        self._attr_name = name
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:{unique_suffix}"

    async def async_press(self) -> None:
        effects = catalog_items(self.coordinator.data, "effects")
        if not effects:
            return
        if self._step == 0:
            effect = secrets.choice(effects)
        else:
            active = read_field(self._state.data, "active_effect_id")
            index = next(
                (idx for idx, effect in enumerate(effects) if item_id(effect) == active),
                -1,
            )
            effect = effects[(index + self._step) % len(effects)]
        await self._entry.runtime_data.client.apply_effect(item_id(effect))
        await self._state.async_request_refresh()


class HypercolorIdentifyDeviceButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Identify"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], device: Any) -> None:
        runtime = entry.runtime_data
        self._entry = entry
        self._device_id = str(read_field(device, "id"))
        self._attr_device_info = child_device_info(runtime, device)
        self._attr_unique_id = f"{runtime.server.instance_id}:device:{self._device_id}:identify"

    async def async_press(self) -> None:
        await self._entry.runtime_data.client.identify_device(self._device_id)
