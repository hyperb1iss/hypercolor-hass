from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hypercolor.models import DeviceSummary

from .const import CONF_CHANNELS_AUDIO
from .entity import (
    HypercolorDeviceEntity,
    HypercolorEntity,
    add_configured_device_entities,
    hub_device_info,
)
from .models import device_enabled
from .runtime_data import HypercolorRuntimeData

_AUDIO_DEVICE_DEFAULT = "default"
_AUDIO_DEVICE_NONE = "none"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SwitchEntity] = []
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.append(HypercolorAudioReactiveSwitch(entry))
    async_add_entities(entities)
    add_configured_device_entities(entry, async_add_entities, HypercolorDeviceEnabledSwitch)


class HypercolorAudioReactiveSwitch(HypercolorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "audio_reactive"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_reactive"

    @property
    def is_on(self) -> bool | None:
        devices = self.snapshot.audio.devices
        return audio_device_enabled(devices.current if devices is not None else None)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._runtime.async_mutate(
            lambda: self._runtime.client.set_audio_device(_AUDIO_DEVICE_DEFAULT)
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._runtime.async_mutate(
            lambda: self._runtime.client.set_audio_device(_AUDIO_DEVICE_NONE)
        )


class HypercolorDeviceEnabledSwitch(HypercolorDeviceEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "enabled"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], device: DeviceSummary) -> None:
        super().__init__(entry, device)
        runtime = entry.runtime_data
        self._attr_unique_id = f"{runtime.server.instance_id}:device:{self._device_id}:enabled"

    @property
    def is_on(self) -> bool | None:
        return device_enabled(device) if (device := self._device) is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        async def operation() -> None:
            await self._runtime.client.update_device(self._device_id, enabled=True)

        await self._runtime.async_mutate(operation)

    async def async_turn_off(self, **kwargs: Any) -> None:
        async def operation() -> None:
            await self._runtime.client.update_device(self._device_id, enabled=False)

        await self._runtime.async_mutate(operation)


def audio_device_enabled(device_id: str | None) -> bool | None:
    if device_id is None:
        return None
    return device_id.lower() not in {"", "disabled", _AUDIO_DEVICE_NONE}
