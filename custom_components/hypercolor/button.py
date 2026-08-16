from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hypercolor.models import Device

from .entity import (
    HypercolorDeviceEntity,
    HypercolorEntity,
    add_configured_device_entities,
    hub_device_info,
)
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[ButtonEntity] = [
        HypercolorActionButton(
            entry,
            name="Discover devices",
            unique_suffix="discover_devices",
            action=lambda: runtime.async_mutate(runtime.client.discover_devices),
        ),
        HypercolorEffectNavigationButton(entry, "Previous effect", "previous_effect", -1),
        HypercolorEffectNavigationButton(entry, "Next effect", "next_effect", 1),
        HypercolorEffectNavigationButton(entry, "Random effect", "random_effect", 0),
        HypercolorActionButton(
            entry,
            name="Stop effect",
            unique_suffix="stop_effect",
            action=runtime.async_stop_effect,
        ),
    ]
    async_add_entities(entities)
    add_configured_device_entities(entry, async_add_entities, HypercolorIdentifyDeviceButton)


class HypercolorActionButton(HypercolorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        *,
        name: str,
        unique_suffix: str,
        action: Callable[[], Awaitable[object]],
    ) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._action = action
        self._attr_name = name
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:{unique_suffix}"

    async def async_press(self) -> None:
        await self._action()


class HypercolorEffectNavigationButton(HypercolorEntity, ButtonEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        name: str,
        unique_suffix: str,
        step: int,
    ) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._step = step
        self._attr_name = name
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:{unique_suffix}"

    async def async_press(self) -> None:
        effects = self.snapshot.catalog.effects.items
        if not effects:
            return
        if self._step == 0:
            effect = secrets.choice(effects)
        else:
            active_id = self.snapshot.state.active_effect_id
            index = next(
                (idx for idx, effect in enumerate(effects) if effect.id == active_id),
                -1,
            )
            effect = effects[(index + self._step) % len(effects)]
        await self._runtime.async_mutate(lambda: self._runtime.client.apply_effect(effect.id))


class HypercolorIdentifyDeviceButton(HypercolorDeviceEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Identify"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], device: Device) -> None:
        super().__init__(entry, device)
        runtime = entry.runtime_data
        self._attr_unique_id = f"{runtime.server.instance_id}:device:{self._device_id}:identify"

    async def async_press(self) -> None:
        await self._runtime.async_mutate(
            lambda: self._runtime.client.identify_device(self._device_id)
        )
