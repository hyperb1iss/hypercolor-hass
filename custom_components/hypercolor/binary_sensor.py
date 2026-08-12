from __future__ import annotations

from time import monotonic

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_AUDIO_BEAT_HOLD_MS,
    CONF_CHANNELS_AUDIO,
    CONF_DISCONNECT_GRACE_S,
    DEFAULT_AUDIO_BEAT_HOLD_MS,
    DEFAULT_DISCONNECT_GRACE_S,
)
from .entity import HypercolorEntity, HypercolorWebsocketEntity, hub_device_info
from .runtime_data import ConnectionSource, HypercolorRuntimeData


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
        self._remove_timer: CALLBACK_TYPE | None = None
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:connected"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_timer)
        self.async_on_remove(
            self._entry.runtime_data.connection_state.add_listener(self._connection_updated)
        )
        self._connection_updated()

    @callback
    def _connection_updated(self) -> None:
        self._cancel_timer()
        grace_s = int(self._entry.options.get(CONF_DISCONNECT_GRACE_S, DEFAULT_DISCONNECT_GRACE_S))
        if (
            grace_s > 0
            and not self._entry.runtime_data.connection_state.sources[
                ConnectionSource.WEBSOCKET
            ].connected
        ):
            self._remove_timer = async_call_later(
                self.hass,
                grace_s,
                self._connection_grace_expired,
            )
        self.async_write_ha_state()

    @callback
    def _connection_grace_expired(self, *_: object) -> None:
        self._remove_timer = None
        self.async_write_ha_state()

    @callback
    def _cancel_timer(self) -> None:
        if self._remove_timer is not None:
            self._remove_timer()
            self._remove_timer = None

    @property
    def is_on(self) -> bool:
        grace_s = int(self._entry.options.get(CONF_DISCONNECT_GRACE_S, DEFAULT_DISCONNECT_GRACE_S))
        return self._entry.runtime_data.connection_state.is_source_connected(
            ConnectionSource.WEBSOCKET,
            grace_s,
        )


class HypercolorAudioBeatBinarySensor(HypercolorWebsocketEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.SOUND
    _attr_has_entity_name = True
    _attr_name = "Audio beat"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._remove_timer: CALLBACK_TYPE | None = None
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_beat"

    @property
    def is_on(self) -> bool:
        beat_until = self.snapshot.audio.beat_until
        return beat_until is not None and monotonic() <= beat_until

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


class HypercolorAudioReactiveBinarySensor(HypercolorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Audio reactive active"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_reactive_active"

    @property
    def is_on(self) -> bool:
        return self.snapshot.active_effect_audio_reactive
