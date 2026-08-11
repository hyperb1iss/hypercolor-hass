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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .brightness import daemon_to_ha, ha_to_daemon
from .client import async_stop_effect
from .const import CONF_PER_DEVICE_ENTITIES, OPTIONS_DEFAULTS
from .entity import (
    catalog_items,
    child_device_info,
    control_scalar,
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
        self._last_effect_id, self._last_preset_id = self._running_effect_ref()

    @callback
    def _handle_coordinator_update(self) -> None:
        # The daemon forgets the active effect (and the preset it was applied
        # with) when rendering stops, so keep the last running pair to resume
        # the full look on a plain turn-on, not just the bare effect.
        effect_id, preset_id = self._running_effect_ref()
        if effect_id:
            self._last_effect_id = effect_id
            self._last_preset_id = preset_id
        super()._handle_coordinator_update()

    def _running_effect_ref(self) -> tuple[str | None, str | None]:
        effect_id = read_field(self.coordinator.data, "active_effect_id")
        preset_id = read_field(self.coordinator.data, "active_preset")
        return (
            str(effect_id) if effect_id else None,
            str(preset_id) if preset_id else None,
        )

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
        state = self.coordinator.data
        cover_image_url = read_field(state, "active_effect_cover_image_url")
        active_id = read_field(state, "active_effect_id")
        active_detail = read_field(state, "active_effect_detail")
        catalog_entry = active_effect_entry(
            self._catalog.data,
            active_id,
            read_field(state, "active_effect"),
        )
        metadata = effect_metadata(catalog_entry, active_detail)
        return {
            "active_effect": self.effect,
            "active_effect_id": active_id,
            "active_effect_cover_image_url": cover_image_url,
            "device_count": read_field(state, "device_count"),
            # `effect_image` mirrors the SignalRGB attribute the card reads for
            # its palette/background source; keep it aliased to the cover URL.
            "effect_image": cover_image_url,
            "scene_count": read_field(state, "scene_count"),
            "active_scene": read_field(state, "active_scene_name"),
            "active_scene_id": read_field(state, "active_scene"),
            "zone_count": len(renderable_zones(state)),
            # Card-facing effect metadata sourced from the catalog + running
            # effect. These are the attributes hyper-light-card renders in the
            # effect-info panel and the generic control surface.
            "effect_description": metadata["description"],
            "effect_publisher": metadata["publisher"],
            "effect_audio_reactive": metadata["audio_reactive"],
            "effect_tags": metadata["tags"],
            "effect_category": metadata["category"],
            "effect_version": metadata["version"],
            "effect_controls": effect_controls_payload(active_detail),
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
        elif not self.is_on and (
            resume := self._last_effect_id or first_effect_id(self._catalog.data)
        ):
            preset = self._last_preset_id if resume == self._last_effect_id else None
            await client.apply_effect(resume, preset_id=preset)

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await async_stop_effect(self._entry.runtime_data.client)
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


def active_effect_entry(catalog: Any, active_id: Any, active_name: Any) -> Any | None:
    """The catalog record for the running effect, matched by id then name."""
    effects = _catalog_effects(catalog)
    if not effects:
        return None
    if active_id is not None:
        for effect in effects:
            if item_id(effect) == str(active_id):
                return effect
    if active_name:
        for effect in effects:
            if item_name(effect) == str(active_name):
                return effect
    return None


def effect_metadata(catalog_entry: Any, active_detail: Any) -> dict[str, Any]:
    """Card-facing metadata for the running effect.

    Description/author/tags/category/version come from the catalog record;
    audio-reactivity prefers the live effect detail and falls back to the
    catalog flag so the card lights up the audio badge even before the first
    state push carries an explicit value.
    """
    audio_reactive = read_field(active_detail, "audio_reactive")
    if audio_reactive is None:
        audio_reactive = read_field(catalog_entry, "audio_reactive", False)
    tags = read_field(catalog_entry, "tags", []) or []
    return {
        "description": read_field(catalog_entry, "description"),
        "publisher": read_field(catalog_entry, "author", read_field(catalog_entry, "publisher")),
        "audio_reactive": bool(audio_reactive),
        "tags": [str(tag) for tag in tags] if isinstance(tags, list) else [],
        "category": read_field(catalog_entry, "category"),
        "version": read_field(catalog_entry, "version"),
    }


def effect_controls_payload(active_detail: Any) -> list[dict[str, Any]]:
    """Normalize the running effect's controls for the card.

    Each entry is a flat, JSON-serializable descriptor the card renders as a
    slider/toggle/select/color without needing per-effect number entities.
    Current values prefer the live ``control_values`` map, falling back to the
    control's own default.
    """
    controls = read_field(active_detail, "controls", []) or []
    if not isinstance(controls, list):
        return []
    values = read_field(active_detail, "control_values", {}) or {}
    payload: list[dict[str, Any]] = []
    for control in controls:
        control_id = read_field(control, "id")
        if control_id is None:
            continue
        value = control_scalar(read_field(values, control_id))
        if value is None:
            value = control_scalar(read_field(control, "value", read_field(control, "default")))
        if value is None:
            value = control_scalar(read_field(control, "default_value"))
        descriptor: dict[str, Any] = {
            "id": str(control_id),
            "label": str(read_field(control, "name", read_field(control, "label", control_id))),
            # Canonical widget kind the card renders directly (number/boolean/
            # enum/color/other). The daemon/client name the widget under
            # `type`, `control_type`, or `kind` depending on the payload path;
            # collapse them all to one vocabulary here so the card never guesses.
            "kind": _canonical_control_kind(control),
            "min": read_field(control, "min", read_field(control, "min_")),
            "max": read_field(control, "max", read_field(control, "max_")),
            "step": read_field(control, "step"),
            "value": value,
        }
        options = _control_options(control)
        if options is not None:
            descriptor["options"] = options
        payload.append(descriptor)
    return payload


_BOOLEAN_KINDS = frozenset({"boolean", "bool", "toggle", "switch", "checkbox"})
_COLOR_KINDS = frozenset({"color", "color_picker", "colorpicker", "rgb", "rgba"})
_ENUM_KINDS = frozenset({"enum", "select", "dropdown", "combobox", "choice", "variant"})
_NUMBER_KINDS = frozenset({"number", "slider", "float", "int", "integer", "range"})


def _canonical_control_kind(control: Any) -> str:
    """Collapse the daemon's widget vocabulary to a card-renderable kind.

    Returns one of ``number``/``boolean``/``enum``/``color`` for controls the
    card can faithfully render and round-trip, or ``other`` for controls it has
    no safe widget for (text/gradient/rect/asset) so the card skips them rather
    than mis-rendering them as sliders that corrupt state on interaction.
    """
    token = str(
        read_field(
            control,
            "type",
            read_field(control, "control_type", read_field(control, "kind", "")),
        )
        or ""
    ).lower()
    if token in _BOOLEAN_KINDS:
        return "boolean"
    if token in _COLOR_KINDS:
        return "color"
    if token in _ENUM_KINDS:
        return "enum"
    if token in _NUMBER_KINDS:
        return "number"
    # No recognized widget token; a choice list still implies a selector.
    if _control_options(control):
        return "enum"
    return "other"


def _control_options(control: Any) -> list[str] | None:
    for key in ("options", "labels", "variants", "choices"):
        raw = read_field(control, key)
        if isinstance(raw, list) and raw:
            return [_option_label(item) for item in raw]
    return None


def _option_label(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("label", "name", "id", "value"):
            if (value := item.get(key)) is not None:
                return str(value)
    return str(item)


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


def first_effect_id(catalog: Any) -> str | None:
    effects = _catalog_effects(catalog)
    if not effects:
        return None
    return item_id(effects[0])


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
