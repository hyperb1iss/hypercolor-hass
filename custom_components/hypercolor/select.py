from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hypercolor.models import AudioDeviceInfo, EffectPresetSummary, LayoutSummary, SceneSummary

from .const import CONF_CHANNELS_AUDIO
from .entity import HypercolorEntity, hub_device_info
from .models import CatalogIndex
from .runtime_data import HypercolorRuntimeData

type CatalogKind = Literal["scenes", "layouts"]
type SelectIndex = CatalogIndex[SceneSummary] | CatalogIndex[LayoutSummary]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SelectEntity] = [
        HypercolorCatalogSelect(
            entry,
            kind="scenes",
            translation_key="scene",
            unique_suffix="scene",
            action=entry.runtime_data.client.activate_scene,
        ),
        HypercolorCatalogSelect(
            entry,
            kind="layouts",
            translation_key="layout",
            unique_suffix="layout",
            action=entry.runtime_data.client.apply_layout,
        ),
        HypercolorPresetSelect(entry),
    ]
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.append(HypercolorAudioDeviceSelect(entry))
    async_add_entities(entities)


class HypercolorCatalogSelect(HypercolorEntity, SelectEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry[HypercolorRuntimeData],
        *,
        kind: CatalogKind,
        translation_key: str,
        unique_suffix: str,
        action: Callable[[str], Awaitable[object]],
    ) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._kind = kind
        self._action = action
        self._attr_translation_key = translation_key
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:{unique_suffix}"

    @property
    def options(self) -> list[str]:
        return self._index.options

    @property
    def current_option(self) -> str | None:
        state = self.snapshot.state
        if self._kind == "scenes":
            active_id = state.scene.id
        else:
            active_id = state.active_layout.id if state.active_layout is not None else None
        return self._index.label(active_id)

    async def async_select_option(self, option: str) -> None:
        selected_id = self._index.resolve(option)
        await self._runtime.async_mutate(lambda: self._action(selected_id))

    @property
    def _index(self) -> SelectIndex:
        catalog = self.snapshot.catalog
        if self._kind == "scenes":
            return catalog.scenes
        return catalog.layouts


class HypercolorPresetSelect(HypercolorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "preset"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:preset"

    @property
    def options(self) -> list[str]:
        return self._index.options

    @property
    def current_option(self) -> str | None:
        return self._index.label(self.snapshot.state.active_preset_id)

    async def async_select_option(self, option: str) -> None:
        preset = self._index.by_id[self._index.resolve(option)]
        await self._runtime.async_mutate(
            lambda: self._runtime.client.apply_effect_preset(preset.effect_id, preset.id)
        )

    @property
    def _index(self) -> CatalogIndex[EffectPresetSummary]:
        return self.snapshot.active_effect_presets


class HypercolorAudioDeviceSelect(HypercolorEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "audio_device"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_device"

    @property
    def options(self) -> list[str]:
        return self._index.options

    @property
    def current_option(self) -> str | None:
        devices = self.snapshot.audio.devices
        return self._index.label(devices.current) if devices is not None else None

    async def async_select_option(self, option: str) -> None:
        device_id = self._index.resolve(option)
        await self._runtime.async_mutate(lambda: self._runtime.client.set_audio_device(device_id))

    @property
    def _index(self) -> CatalogIndex[AudioDeviceInfo]:
        devices = self.snapshot.audio.devices
        return CatalogIndex.build(devices.devices if devices is not None else ())
