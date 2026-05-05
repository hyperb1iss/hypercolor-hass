from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CHANNELS_AUDIO, CONF_CHANNELS_METRICS
from .entity import hub_device_info, read_field
from .runtime_data import HypercolorRuntimeData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities: list[SensorEntity] = [
        HypercolorActiveEffectSensor(entry),
        HypercolorFpsSensor(entry),
    ]
    if entry.options.get(CONF_CHANNELS_METRICS, False):
        entities.append(HypercolorRenderTimeSensor(entry))
    if entry.options.get(CONF_CHANNELS_AUDIO, False):
        entities.append(HypercolorAudioEnergySensor(entry))
    async_add_entities(entities)


class HypercolorActiveEffectSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Active effect"

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["state"])
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:active_effect"

    @property
    def native_value(self) -> str | None:
        value = read_field(self.coordinator.data, "active_effect")
        return str(value) if value else None


class HypercolorFpsSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "FPS"
    _attr_native_unit_of_measurement = "fps"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["state"])
        self._metrics = runtime.coordinators["metrics"]
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:fps"

    @property
    def native_value(self) -> float | None:
        metrics_value = _first_number(self._metrics.data, "fps", "render_fps")
        if metrics_value is not None:
            return metrics_value
        render_loop = read_field(self.coordinator.data, "render_loop", {})
        return _first_number(render_loop, "fps", "target_fps", "actual_fps")


class HypercolorRenderTimeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Render time"
    _attr_native_unit_of_measurement = "ms"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["metrics"])
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:render_time"

    @property
    def native_value(self) -> float | None:
        return _first_number(self.coordinator.data, "render_time_ms", "frame_time_ms")


class HypercolorAudioEnergySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Audio energy"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData]) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["audio"])
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:audio_energy"

    @property
    def native_value(self) -> float | None:
        spectrum = read_field(self.coordinator.data, "spectrum", {})
        return _first_number(spectrum, "level", "energy")


def _first_number(data: Any, *keys: str) -> float | None:
    for key in keys:
        value = read_field(data, key)
        if isinstance(value, (int, float)):
            return float(value)
    return None
