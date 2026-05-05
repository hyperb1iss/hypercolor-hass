from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_AUDIO_BEAT_HOLD_MS,
    CONF_CHANNELS_AUDIO,
    DEFAULT_AUDIO_BEAT_HOLD_MS,
)
from .entity import catalog_items, hub_device_info, item_id, item_name, read_field
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[BinarySensorEntity] = [HypercolorConnectedBinarySensor(entry)]
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.extend(
            [
                HypercolorAudioBeatBinarySensor(entry),
                HypercolorAudioReactiveBinarySensor(entry),
            ]
        )
    async_add_entities(entities)


class HypercolorConnectedBinarySensor(BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_has_entity_name = True
    _attr_name = "Connected"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        self._entry = entry
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:connected"

    @property
    def is_on(self) -> bool:
        state = self._entry.runtime_data.connection_state
        if state.connected:
            return True
        grace_s = int(self._entry.options.get("disconnect_grace_s", 5))
        if state.last_disconnected_at is None:
            return False
        elapsed = datetime.now(UTC) - state.last_disconnected_at
        return elapsed.total_seconds() < grace_s


class HypercolorAudioBeatBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_has_entity_name = True
    _attr_name = "Audio beat"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["audio"])
        self._entry = entry
        self._remove_timer: CALLBACK_TYPE | None = None
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_beat"

    @property
    def is_on(self) -> bool:
        spectrum = (self.coordinator.data or {}).get("spectrum") or {}
        beat_until = spectrum.get("beat_until")
        if isinstance(beat_until, datetime):
            return datetime.now(UTC) <= beat_until
        return bool(spectrum.get("beat", False))

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.is_on:
            if self._remove_timer is not None:
                self._remove_timer()
            hold_ms = int(
                self._entry.options.get(
                    CONF_AUDIO_BEAT_HOLD_MS,
                    DEFAULT_AUDIO_BEAT_HOLD_MS,
                )
            )
            self._remove_timer = async_call_later(
                self.hass,
                hold_ms / 1000,
                self._beat_expired,
            )
        super()._handle_coordinator_update()

    @callback
    def _beat_expired(self, *_: object) -> None:
        self._remove_timer = None
        self.async_write_ha_state()


class HypercolorAudioReactiveBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Audio reactive active"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["state"])
        self._catalog = runtime.coordinators["catalog"]
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_reactive_active"

    @property
    def is_on(self) -> bool:
        return active_effect_audio_reactive(self.coordinator.data, self._catalog.data)


def active_effect_audio_reactive(state_data: object, catalog_data: object) -> bool:
    active = read_field(state_data, "active_effect_detail")
    audio_reactive = read_field(active, "audio_reactive")
    if audio_reactive is not None:
        return bool(audio_reactive)

    active_id = read_field(state_data, "active_effect_id")
    active_name = read_field(state_data, "active_effect")
    for effect in catalog_items(catalog_data, "effects"):
        if active_id is not None and item_id(effect) == active_id:
            return bool(read_field(effect, "audio_reactive", False))
    if active_id is None and active_name:
        for effect in catalog_items(catalog_data, "effects"):
            if item_name(effect) == active_name:
                return bool(read_field(effect, "audio_reactive", False))
    return False
