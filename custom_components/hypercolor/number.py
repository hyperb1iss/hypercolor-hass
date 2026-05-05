from __future__ import annotations

import re
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LIVE_CONTROLS_ENABLED, LIVE_CONTROL_IDS, OPTIONS_DEFAULTS
from .entity import hub_device_info, read_field
from .runtime_data import HypercolorRuntimeData

_DEFAULTS = {
    "brightness": (0.0, 100.0, 1.0),
    "speed": (0.0, 100.0, 1.0),
    "hue_shift": (0.0, 360.0, 1.0),
    "intensity": (0.0, 100.0, 1.0),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not entry.options.get(
        CONF_LIVE_CONTROLS_ENABLED,
        OPTIONS_DEFAULTS[CONF_LIVE_CONTROLS_ENABLED],
    ):
        return
    async_add_entities(
        [HypercolorLiveControlNumber(entry, control_id) for control_id in LIVE_CONTROL_IDS]
    )


class HypercolorLiveControlNumber(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], control_id: str) -> None:
        runtime = entry.runtime_data
        super().__init__(runtime.coordinators["state"])
        self._entry = entry
        self._control_id = control_id
        self._attr_name = control_id.replace("_", " ").title()
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:control:{control_id}"

    @property
    def available(self) -> bool:
        return super().available and self._control is not None

    @property
    def native_min_value(self) -> float:
        control = self._control
        if control is not None and (value := read_field(control, "min")) is not None:
            return float(value)
        return _DEFAULTS[self._control_id][0]

    @property
    def native_max_value(self) -> float:
        control = self._control
        if control is not None and (value := read_field(control, "max")) is not None:
            return float(value)
        return _DEFAULTS[self._control_id][1]

    @property
    def native_step(self) -> float:
        control = self._control
        if control is not None and (value := read_field(control, "step")) is not None:
            return float(value)
        return _DEFAULTS[self._control_id][2]

    @property
    def native_value(self) -> float | None:
        control = self._control
        if control is None:
            return None
        active = read_field(self.coordinator.data, "active_effect_detail")
        values = read_field(active, "control_values", {})
        value = read_field(values, read_field(control, "id"))
        if value is None:
            value = read_field(control, "value", read_field(control, "default"))
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        control = self._control
        if control is None:
            return
        await self._entry.runtime_data.client.update_controls(
            {str(read_field(control, "id")): value}
        )
        await self.coordinator.async_request_refresh()

    @property
    def _control(self) -> Any | None:
        active = read_field(self.coordinator.data, "active_effect_detail")
        for control in read_field(active, "controls", []) or []:
            names = {
                _normalize(str(read_field(control, "id", ""))),
                _normalize(str(read_field(control, "label", ""))),
            }
            if _normalize(self._control_id) in names:
                return control
        return None


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
