from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.redact import async_redact_data

from .const import TO_REDACT
from .runtime_data import HypercolorRuntimeData


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
) -> dict[str, Any]:
    runtime = entry.runtime_data
    return async_redact_data(
        {
            "config": {**entry.data, **entry.options},
            "server": asdict(runtime.server),
            "connection": runtime.connection_state.snapshot(),
            "coordinators": {
                name: coordinator.last_update_success
                for name, coordinator in runtime.coordinators.items()
            },
        },
        TO_REDACT,
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[HypercolorRuntimeData],
    device: DeviceEntry,
) -> dict[str, Any]:
    return async_redact_data(
        {
            "config_entry_id": entry.entry_id,
            "device": {
                "id": device.id,
                "identifiers": [list(identifier) for identifier in device.identifiers],
                "name": device.name,
            },
        },
        TO_REDACT,
    )
