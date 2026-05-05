from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import asdict
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, selector

from .const import DOMAIN
from .runtime_data import HypercolorRuntimeData

CONF_CONFIG_ENTRY_ID = "config_entry_id"

SERVICE_APPLY_EFFECT = "apply_effect"
SERVICE_SET_CONTROL = "set_control"
SERVICE_ACTIVATE_SCENE = "activate_scene"
SERVICE_ACTIVATE_PROFILE = "activate_profile"
SERVICE_APPLY_LAYOUT = "apply_layout"
SERVICE_IDENTIFY_DEVICE = "identify_device"
SERVICE_RUN_DIAGNOSTICS = "run_diagnostics"


def async_setup_services(hass: HomeAssistant) -> None:
    _register(
        hass,
        SERVICE_APPLY_EFFECT,
        _apply_effect,
        _schema({vol.Required("effect_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_SET_CONTROL,
        _set_control,
        _schema({vol.Required("control_name"): cv.string, vol.Required("value"): object}),
    )
    _register(
        hass,
        SERVICE_ACTIVATE_SCENE,
        _activate_scene,
        _schema({vol.Required("scene_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_ACTIVATE_PROFILE,
        _activate_profile,
        _schema({vol.Required("profile_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_APPLY_LAYOUT,
        _apply_layout,
        _schema({vol.Required("layout_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_IDENTIFY_DEVICE,
        _identify_device,
        _schema(
            {vol.Required("device_id"): cv.string, vol.Optional("duration_ms"): cv.positive_int}
        ),
    )
    _register(
        hass,
        SERVICE_RUN_DIAGNOSTICS,
        _run_diagnostics,
        _schema({}),
        supports_response=SupportsResponse.ONLY,
    )


def _register(
    hass: HomeAssistant,
    service: str,
    handler: Callable[[ServiceCall], Coroutine[Any, Any, ServiceResponse]],
    schema: vol.Schema,
    *,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> None:
    if hass.services.has_service(DOMAIN, service):
        return
    hass.services.async_register(
        DOMAIN,
        service,
        handler,
        schema=schema,
        supports_response=supports_response,
    )


def _schema(fields: dict[Any, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CONFIG_ENTRY_ID): selector.ConfigEntrySelector(
                selector.ConfigEntrySelectorConfig(integration=DOMAIN)
            ),
            **fields,
        }
    )


async def _apply_effect(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.apply_effect(call.data["effect_id"])


async def _set_control(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.update_controls(
        {call.data["control_name"]: call.data["value"]}
    )


async def _activate_scene(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.activate_scene(call.data["scene_id"])


async def _activate_profile(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.apply_profile(call.data["profile_id"])


async def _apply_layout(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.apply_layout(call.data["layout_id"])


async def _identify_device(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.identify_device(
        call.data["device_id"],
        duration_ms=call.data.get("duration_ms"),
    )


async def _run_diagnostics(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    return {
        "config_entry": {
            CONF_NAME: entry.title,
            "entry_id": entry.entry_id,
        },
        "server": asdict(runtime.server),
        "connection": runtime.connection_state.snapshot(),
        "coordinators": {
            name: coordinator.last_update_success
            for name, coordinator in runtime.coordinators.items()
        },
    }


def _entry(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ConfigEntry[HypercolorRuntimeData]:
    entry_id = call.data[CONF_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"Unknown Hypercolor config entry: {entry_id}")
    return entry
