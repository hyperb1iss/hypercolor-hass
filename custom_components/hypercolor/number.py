from __future__ import annotations

import re

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from hypercolor.models import ControlDefinition

from .const import CONF_LIVE_CONTROLS_ENABLED, LIVE_CONTROL_IDS, OPTIONS_DEFAULTS
from .entity import HypercolorEntity, hub_device_info
from .models import control_scalar
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


class HypercolorLiveControlNumber(HypercolorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: ConfigEntry[HypercolorRuntimeData], control_id: str) -> None:
        super().__init__(entry)
        runtime = entry.runtime_data
        self._control_id = control_id
        self._attr_translation_key = control_id
        self._attr_device_info = hub_device_info(runtime, entry.data)
        self._attr_unique_id = f"{runtime.server.instance_id}:control:{control_id}"

    @property
    def available(self) -> bool:
        return super().available and self._control is not None

    @property
    def native_min_value(self) -> float:
        control = self._control
        return control.min if control is not None and control.min is not None else self._default(0)

    @property
    def native_max_value(self) -> float:
        control = self._control
        return control.max if control is not None and control.max is not None else self._default(1)

    @property
    def native_step(self) -> float:
        control = self._control
        return (
            control.step if control is not None and control.step is not None else self._default(2)
        )

    @property
    def native_value(self) -> float | None:
        control = self._control
        active_effect = self.snapshot.state.active_effect
        if control is None or active_effect is None:
            return None
        value = control_scalar(active_effect.control_values.get(control.id))
        if value is None:
            value = control_scalar(control.value)
        if value is None:
            value = control_scalar(control.default)
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        control = self._control
        if control is None:
            return
        await self._runtime.async_mutate(
            lambda: self._runtime.client.update_controls({control.id: value})
        )

    @property
    def _control(self) -> ControlDefinition | None:
        active_effect = self.snapshot.state.active_effect
        if active_effect is None:
            return None
        expected = _normalize(self._control_id)
        return next(
            (
                control
                for control in active_effect.controls
                if expected in {_normalize(control.id), _normalize(control.label)}
            ),
            None,
        )

    def _default(self, index: int) -> float:
        return _DEFAULTS[self._control_id][index]


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
