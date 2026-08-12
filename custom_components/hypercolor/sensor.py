from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNELS_AUDIO, CONF_CHANNELS_METRICS
from .entity import HypercolorEntity, HypercolorWebsocketEntity, hub_device_info
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SensorEntity] = [
        HypercolorActiveEffectSensor(entry),
    ]
    if entry.options.get(CONF_CHANNELS_METRICS, False):
        entities.extend(
            [
                HypercolorFpsSensor(entry),
                HypercolorRenderTimeSensor(entry),
            ]
        )
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.append(HypercolorAudioEnergySensor(entry))
    async_add_entities(entities)


class HypercolorActiveEffectSensor(HypercolorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Active effect"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:active_effect"

    @property
    def native_value(self) -> str | None:
        return self.snapshot.state.active_effect_name


class HypercolorFpsSensor(HypercolorWebsocketEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "FPS"
    _attr_native_unit_of_measurement = "fps"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:fps"

    @property
    def native_value(self) -> float | None:
        return _nested_number(self.snapshot.metrics, "fps", "actual")


class HypercolorRenderTimeSensor(HypercolorWebsocketEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Render time"
    _attr_native_unit_of_measurement = "ms"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:render_time"

    @property
    def native_value(self) -> float | None:
        return _nested_number(self.snapshot.metrics, "frame_time", "avg_ms")


class HypercolorAudioEnergySensor(HypercolorWebsocketEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Audio energy"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_energy"

    @property
    def native_value(self) -> float | None:
        spectrum = self.snapshot.audio.spectrum
        return spectrum.level if spectrum is not None else None


def _nested_number(data: dict[str, Any], section: str, field: str) -> float | None:
    values = data.get(section)
    if not isinstance(values, dict):
        return None
    value = values.get(field)
    return float(value) if isinstance(value, (int, float)) else None
