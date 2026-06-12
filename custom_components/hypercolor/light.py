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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .brightness import daemon_to_ha, ha_to_daemon
from .const import CONF_PER_DEVICE_ENTITIES, OPTIONS_DEFAULTS
from .entity import (
    catalog_items,
    child_device_info,
    hub_device_info,
    item_id,
    item_name,
    read_field,
)
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[LightEntity] = [HypercolorMasterLight(entry)]
    enabled_devices = set(
        entry.options.get(
            CONF_PER_DEVICE_ENTITIES,
            OPTIONS_DEFAULTS[CONF_PER_DEVICE_ENTITIES],
        )
    )
    devices = entry.runtime_data.coordinators["devices"].data or []
    entities.extend(
        HypercolorDeviceLight(entry, device)
        for device in devices
        if str(read_field(device, "id")) in enabled_devices
    )
    async_add_entities(entities)

    state = entry.runtime_data.coordinators["state"]
    known_zone_ids: set[str] = set()

    def _sync_zone_entities() -> None:
        fresh = [
            zone
            for zone in renderable_zones(state.data)
            if str(read_field(zone, "id")) not in known_zone_ids
        ]
        if not fresh:
            return
        known_zone_ids.update(str(read_field(zone, "id")) for zone in fresh)
        async_add_entities(
            HypercolorZoneLight(entry, str(read_field(zone, "id"))) for zone in fresh
        )

    _sync_zone_entities()
    entry.async_on_unload(state.async_add_listener(_sync_zone_entities))


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
        cover_image_url = read_field(
            self.coordinator.data,
            "active_effect_cover_image_url",
        )
        return {
            "active_effect": self.effect,
            "active_effect_id": read_field(self.coordinator.data, "active_effect_id"),
            "active_effect_cover_image_url": cover_image_url,
            "device_count": read_field(self.coordinator.data, "device_count"),
            "effect_image": cover_image_url,
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


class HypercolorDeviceLight(CoordinatorEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], device: Any) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["devices"])
        self._entry = entry
        self._device_id = str(read_field(device, "id"))
        self._attr_device_info = child_device_info(runtime, device)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_unique_id = f"{runtime.server.instance_id}:device:{self._device_id}:light"

    @property
    def brightness(self) -> int | None:
        if device := self._device:
            value = read_field(device, "brightness")
            return daemon_to_ha(int(value)) if value is not None else None
        return None

    @property
    def is_on(self) -> bool | None:
        if device := self._device:
            return (
                bool(read_field(device, "enabled", True)) and read_field(device, "status") != "off"
            )
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        fields: dict[str, Any] = {"enabled": True}
        if ATTR_BRIGHTNESS in kwargs:
            fields["brightness"] = ha_to_daemon(int(kwargs[ATTR_BRIGHTNESS]))
        await self._entry.runtime_data.client.update_device(self._device_id, **fields)
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


class HypercolorZoneLight(CoordinatorEntity, LightEntity):
    """One zone (render group) of the active scene.

    Zones are scene-scoped: when the active scene changes, entities for
    zones that no longer exist go unavailable, and new zones appear.
    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], zone_id: str) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["state"])
        self._entry = entry
        self._zone_id = zone_id
        self._catalog = runtime.coordinators["catalog"]
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_unique_id = f"{runtime.server.instance_id}:zone:{zone_id}"

    @property
    def available(self) -> bool:
        return super().available and self._zone is not None

    @property
    def name(self) -> str | None:
        if zone := self._zone:
            return str(read_field(zone, "name", self._zone_id))
        return f"Zone {self._zone_id}"

    @property
    def brightness(self) -> int | None:
        if zone := self._zone:
            value = read_field(zone, "brightness")
            if value is not None:
                return max(0, min(255, round(float(value) * 255)))
        return None

    @property
    def is_on(self) -> bool | None:
        if zone := self._zone:
            return bool(read_field(zone, "enabled", True))
        return None

    @property
    def effect(self) -> str | None:
        zone = self._zone
        if zone is None:
            return None
        effect_id = read_field(zone, "effect_id")
        if not effect_id:
            return None
        return effect_name_for_id(self._catalog.data, str(effect_id))

    @property
    def effect_list(self) -> list[str] | None:
        return effect_names(self._catalog.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone
        layout = read_field(zone, "layout")
        outputs = read_field(layout, "zones", []) or []
        return {
            "zone_id": self._zone_id,
            "role": read_field(zone, "role"),
            "effect_id": read_field(zone, "effect_id"),
            "preset_id": read_field(zone, "preset_id"),
            "output_count": len(outputs) if isinstance(outputs, list) else None,
            "scene_id": read_field(self.coordinator.data, "active_scene"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        client = self._entry.runtime_data.client
        scene_id = self._scene_id()
        updates: dict[str, Any] = {}
        if ATTR_BRIGHTNESS in kwargs:
            updates["brightness"] = round(int(kwargs[ATTR_BRIGHTNESS]) / 255, 4)
        if not self.is_on:
            updates["enabled"] = True
        if updates:
            await client.update_zone(scene_id, self._zone_id, **updates)

        effect = kwargs.get(ATTR_EFFECT)
        if effect:
            await client.apply_effect(
                effect_id_for_name(self._catalog.data, str(effect)),
                render_group=self._zone_id,
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        client = self._entry.runtime_data.client
        await client.update_zone(self._scene_id(), self._zone_id, enabled=False)
        await self.coordinator.async_request_refresh()

    def _scene_id(self) -> str:
        scene_id = read_field(self.coordinator.data, "active_scene")
        if not scene_id:
            raise HomeAssistantError("No active Hypercolor scene")
        return str(scene_id)

    @property
    def _zone(self) -> Any | None:
        for zone in renderable_zones(self.coordinator.data):
            if str(read_field(zone, "id")) == self._zone_id:
                return zone
        return None


def renderable_zones(state: Any) -> list[Any]:
    """Zones of the active scene that render to LEDs (not display faces)."""
    zones = read_field(state, "zones", []) or []
    if not isinstance(zones, list):
        return []
    return [zone for zone in zones if read_field(zone, "role") != "display"]


def effect_names(catalog: Any) -> list[str] | None:
    effects = _catalog_effects(catalog)
    if effects is None:
        return None
    return [item_name(effect) for effect in effects]


def effect_id_for_name(catalog: Any, name: str) -> str:
    effects = _catalog_effects(catalog)
    if effects is None:
        return name
    for effect in effects:
        if item_name(effect) == name:
            return item_id(effect)
    return name


def effect_name_for_id(catalog: Any, effect_id: str) -> str:
    effects = _catalog_effects(catalog)
    if effects is None:
        return effect_id
    for effect in effects:
        if item_id(effect) == effect_id:
            return item_name(effect)
    return effect_id


def _catalog_effects(catalog: Any) -> list[Any] | None:
    effects = catalog_items(catalog, "effects")
    return effects or None
