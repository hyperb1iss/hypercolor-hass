from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .brightness import daemon_to_ha, ha_to_daemon
from .entity import hub_device_info, read_field
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HypercolorMasterLight(entry)])


class HypercolorMasterLight(CoordinatorEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["state"])
        self._entry = entry
        self._catalog = runtime.coordinators["catalog"]
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_unique_id = f"{runtime.server.instance_id}:master"

    @property
    def brightness(self) -> int | None:
        value = read_field(self.coordinator.data, "global_brightness")
        return daemon_to_ha(int(value)) if value is not None else None

    @property
    def effect(self) -> str | None:
        value = read_field(self.coordinator.data, "active_effect")
        return str(value) if value else None

    @property
    def effect_list(self) -> list[str] | None:
        return effect_names(self._catalog.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "active_effect": self.effect,
            "device_count": read_field(self.coordinator.data, "device_count"),
            "scene_count": read_field(self.coordinator.data, "scene_count"),
        }

    @property
    def is_on(self) -> bool | None:
        return self.effect is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = self._entry.runtime_data.client
        if ATTR_BRIGHTNESS in kwargs:
            await client.set_brightness(ha_to_daemon(int(kwargs[ATTR_BRIGHTNESS])))

        effect = kwargs.get(ATTR_EFFECT)
        if effect:
            await client.apply_effect(effect_id_for_name(self._catalog.data, str(effect)))

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._entry.runtime_data.client.stop_effect()
        await self.coordinator.async_request_refresh()


def effect_names(catalog: Any) -> list[str] | None:
    effects = _catalog_effects(catalog)
    if effects is None:
        return None
    return [_effect_name(effect) for effect in effects]


def effect_id_for_name(catalog: Any, name: str) -> str:
    effects = _catalog_effects(catalog)
    if effects is None:
        return name
    for effect in effects:
        if _effect_name(effect) == name:
            return _effect_id(effect)
    return name


def _catalog_effects(catalog: Any) -> list[Any] | None:
    if isinstance(catalog, list):
        return catalog
    return None


def _effect_name(effect: Any) -> str:
    return str(read_field(effect, "name", read_field(effect, "id")))


def _effect_id(effect: Any) -> str:
    return str(read_field(effect, "id", read_field(effect, "name")))
