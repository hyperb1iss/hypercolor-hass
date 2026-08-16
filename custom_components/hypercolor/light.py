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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hypercolor.models import ActiveEffect, ControlDefinition, Device, EffectSummary, Zone

from .brightness import daemon_to_ha, ha_to_daemon
from .entity import (
    HypercolorDeviceEntity,
    HypercolorEntity,
    add_configured_device_entities,
    hub_device_info,
)
from .models import CatalogIndex, control_scalar
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = entry.runtime_data
    entities: list[LightEntity] = [HypercolorMasterLight(entry)]
    async_add_entities(entities)
    add_configured_device_entities(entry, async_add_entities, HypercolorDeviceLight)

    known_zone_ids: set[str] = set()

    @callback
    def _sync_zone_entities() -> None:
        fresh = [
            zone
            for zone in runtime.snapshot.state.renderable_zones
            if zone.id not in known_zone_ids
        ]
        if not fresh:
            return
        known_zone_ids.update(zone.id for zone in fresh)
        async_add_entities(HypercolorZoneLight(entry, zone.id) for zone in fresh)

    _sync_zone_entities()
    entry.async_on_unload(runtime.coordinator.async_add_listener(_sync_zone_entities))


class HypercolorMasterLight(HypercolorEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_unique_id = f"{runtime.server.instance_id}:master"
        self._last_effect_id, self._last_preset_id = self._running_effect_ref()

    @callback
    def _handle_coordinator_update(self) -> None:
        effect_id, preset_id = self._running_effect_ref()
        if effect_id:
            self._last_effect_id = effect_id
            self._last_preset_id = preset_id
        super()._handle_coordinator_update()

    def _running_effect_ref(self) -> tuple[str | None, str | None]:
        state = self.snapshot.state
        return state.active_effect_id, state.active_preset_id

    @property
    def brightness(self) -> int:
        return daemon_to_ha(self.snapshot.state.status.global_brightness)

    @property
    def effect(self) -> str | None:
        state = self.snapshot.state
        return (
            self.snapshot.catalog.effects.label(state.active_effect_id) or state.active_effect_name
        )

    @property
    def effect_list(self) -> list[str]:
        return self.snapshot.catalog.effects.options

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.snapshot.state
        summary = self.snapshot.active_effect_summary
        cover_image_url = state.active_effect_cover_image_url
        return {
            "active_effect": state.active_effect_name,
            "active_effect_id": state.active_effect_id,
            "active_preset_id": state.active_preset_id,
            "active_preset_modified": state.active_preset_modified,
            "active_effect_cover_image_url": cover_image_url,
            "device_count": state.status.device_count,
            "effect_image": cover_image_url,
            "scene_count": state.status.scene_count,
            "active_scene": state.active_scene.name if state.active_scene is not None else None,
            "active_scene_id": state.active_scene.id if state.active_scene is not None else None,
            "zone_count": len(state.renderable_zones),
            **effect_metadata(summary),
            "effect_controls": effect_controls_payload(state.active_effect),
        }

    @property
    def is_on(self) -> bool:
        state = self.snapshot.state
        return state.active_effect_id is not None and not state.paused

    async def async_turn_on(self, **kwargs: Any) -> None:
        async def operation() -> None:
            client = self._runtime.client
            if ATTR_BRIGHTNESS in kwargs:
                await client.set_brightness(ha_to_daemon(int(kwargs[ATTR_BRIGHTNESS])))

            effect = kwargs.get(ATTR_EFFECT)
            if effect:
                await client.apply_effect(self.snapshot.catalog.effects.resolve(str(effect)))
            elif self.snapshot.state.paused:
                await client.resume_rendering()
            elif not self.is_on and (
                resume := self._last_effect_id or first_id(self.snapshot.catalog.effects)
            ):
                preset = self._last_preset_id if resume == self._last_effect_id else None
                if preset is not None:
                    await client.apply_effect_preset(resume, preset)
                else:
                    await client.apply_effect(resume)

        await self._runtime.async_mutate(operation)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._runtime.async_mutate(self._runtime.client.pause_rendering)


class HypercolorDeviceLight(HypercolorDeviceEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], device: Device) -> None:
        super().__init__(entry, device)
        runtime = entry.runtime_data
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_unique_id = f"{runtime.server.instance_id}:device:{self._device_id}:light"

    @property
    def brightness(self) -> int | None:
        return daemon_to_ha(device.brightness) if (device := self._device) is not None else None

    @property
    def is_on(self) -> bool | None:
        return device.enabled and device.status != "off" if (device := self._device) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = (
            ha_to_daemon(int(kwargs[ATTR_BRIGHTNESS])) if ATTR_BRIGHTNESS in kwargs else None
        )

        async def operation() -> None:
            await self._runtime.client.update_device(
                self._device_id,
                enabled=True,
                brightness=brightness,
            )

        await self._runtime.async_mutate(operation)

    async def async_turn_off(self, **kwargs: Any) -> None:
        async def operation() -> None:
            await self._runtime.client.update_device(self._device_id, enabled=False)

        await self._runtime.async_mutate(operation)


class HypercolorZoneLight(HypercolorEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_has_entity_name = True
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], zone_id: str) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._zone_id = zone_id
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._attr_unique_id = f"{runtime.server.instance_id}:zone:{zone_id}"

    @property
    def available(self) -> bool:
        return super().available and self._zone is not None

    @property
    def name(self) -> str:
        return zone.name if (zone := self._zone) is not None else f"Zone {self._zone_id}"

    @property
    def brightness(self) -> int | None:
        return _zone_to_ha(zone.brightness) if (zone := self._zone) is not None else None

    @property
    def is_on(self) -> bool | None:
        return zone.enabled if (zone := self._zone) is not None else None

    @property
    def effect(self) -> str | None:
        zone = self._zone
        if zone is None or zone.effect_id is None:
            return None
        return self.snapshot.catalog.effects.label(zone.effect_id) or zone.effect_id

    @property
    def effect_list(self) -> list[str]:
        return self.snapshot.catalog.effects.options

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone
        scene = self.snapshot.state.active_scene
        return {
            "zone_id": self._zone_id,
            "role": zone.role if zone is not None else None,
            "effect_id": zone.effect_id if zone is not None else None,
            "preset_id": zone.preset_id if zone is not None else None,
            "output_count": len(zone.layout.zones) if zone is not None else None,
            "scene_id": scene.id if scene is not None else None,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = (
            round(int(kwargs[ATTR_BRIGHTNESS]) / 255, 4) if ATTR_BRIGHTNESS in kwargs else None
        )
        effect = kwargs.get(ATTR_EFFECT)

        async def operation() -> None:
            client = self._runtime.client
            if brightness is not None or not self.is_on:
                await client.update_zone(
                    self._scene_id(),
                    self._zone_id,
                    brightness=brightness,
                    enabled=True if not self.is_on else None,
                )
            if effect:
                await client.apply_effect(
                    self.snapshot.catalog.effects.resolve(str(effect)),
                    render_group=self._zone_id,
                )

        await self._runtime.async_mutate(operation)

    async def async_turn_off(self, **kwargs: Any) -> None:
        async def operation() -> None:
            await self._runtime.client.update_zone(
                self._scene_id(),
                self._zone_id,
                enabled=False,
            )

        await self._runtime.async_mutate(operation)

    def _scene_id(self) -> str:
        scene = self.snapshot.state.active_scene
        if scene is None:
            raise HomeAssistantError("No active Hypercolor scene")
        return scene.id

    @property
    def _zone(self) -> Zone | None:
        return self.snapshot.state.zone(self._zone_id)


def effect_metadata(effect: EffectSummary | None) -> dict[str, Any]:
    return {
        "effect_description": effect.description if effect is not None else None,
        "effect_publisher": effect.author if effect is not None else None,
        "effect_audio_reactive": effect.audio_reactive if effect is not None else False,
        "effect_tags": list(effect.tags) if effect is not None else [],
        "effect_category": effect.category if effect is not None else None,
        "effect_version": effect.version if effect is not None else None,
    }


def effect_controls_payload(active_effect: ActiveEffect | None) -> list[dict[str, Any]]:
    if active_effect is None:
        return []
    return [
        _control_payload(control, active_effect.control_values.get(control.id))
        for control in active_effect.controls
    ]


def _control_payload(control: ControlDefinition, live_value: Any) -> dict[str, Any]:
    value = control_scalar(live_value)
    if value is None:
        value = control_scalar(control.value)
    if value is None:
        value = control_scalar(control.default)
    payload = {
        "id": control.id,
        "label": control.label,
        "kind": _canonical_control_kind(control),
        "min": control.min,
        "max": control.max,
        "step": control.step,
        "value": value,
    }
    if control.options is not None:
        payload["options"] = list(control.options)
    return payload


def _canonical_control_kind(control: ControlDefinition) -> str:
    if control.type in {"boolean", "bool", "toggle", "switch", "checkbox"}:
        return "boolean"
    if control.type in {"color", "color_picker", "colorpicker", "rgb", "rgba"}:
        return "color"
    if control.type in {"enum", "select", "dropdown", "combobox", "choice", "variant"}:
        return "enum"
    if control.type in {"number", "slider", "float", "int", "integer", "range"}:
        return "number"
    return "enum" if control.options else "other"


def first_id(index: CatalogIndex[EffectSummary]) -> str | None:
    return index.items[0].id if index.items else None


def _zone_to_ha(brightness: float) -> int:
    return max(0, min(255, round(brightness * 255)))
