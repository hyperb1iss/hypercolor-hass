from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import asdict
from pathlib import Path
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
SERVICE_SET_COLOR = "set_color"
SERVICE_SET_CONTROL = "set_control"
SERVICE_ACTIVATE_SCENE = "activate_scene"
SERVICE_CREATE_SCENE = "create_scene"
SERVICE_ACTIVATE_PROFILE = "activate_profile"
SERVICE_SAVE_PROFILE = "save_profile"
SERVICE_APPLY_LAYOUT = "apply_layout"
SERVICE_APPLY_PRESET = "apply_preset"
SERVICE_SAVE_PRESET = "save_preset"
SERVICE_DELETE_PRESET = "delete_preset"
SERVICE_LIST_PRESETS = "list_presets"
SERVICE_IDENTIFY_DEVICE = "identify_device"
SERVICE_SET_DISPLAY_FACE = "set_display_face"
SERVICE_UPLOAD_EFFECT = "upload_effect"
SERVICE_RUN_DIAGNOSTICS = "run_diagnostics"


def async_setup_services(hass: HomeAssistant) -> None:
    _register(
        hass,
        SERVICE_APPLY_EFFECT,
        _apply_effect,
        _schema(
            {
                vol.Optional("effect_id"): cv.string,
                vol.Optional("controls"): dict,
                vol.Optional("transition"): dict,
                vol.Optional("preset_id"): cv.string,
            }
        ),
    )
    _register(
        hass,
        SERVICE_SET_COLOR,
        _set_color,
        _schema(
            {
                vol.Optional("hex"): cv.string,
                vol.Optional("r"): vol.All(int, vol.Range(min=0, max=255)),
                vol.Optional("g"): vol.All(int, vol.Range(min=0, max=255)),
                vol.Optional("b"): vol.All(int, vol.Range(min=0, max=255)),
            }
        ),
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
        SERVICE_CREATE_SCENE,
        _create_scene,
        _schema(
            {
                vol.Required(CONF_NAME): cv.string,
                vol.Optional("description"): cv.string,
                vol.Optional("enabled"): bool,
                vol.Optional("mutation_mode"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        hass,
        SERVICE_ACTIVATE_PROFILE,
        _activate_profile,
        _schema({vol.Required("profile_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_SAVE_PROFILE,
        _save_profile,
        _schema(
            {
                vol.Required(CONF_NAME): cv.string,
                vol.Optional("description"): cv.string,
                vol.Optional("brightness"): vol.All(int, vol.Range(min=0, max=100)),
                vol.Optional("force"): bool,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        hass,
        SERVICE_APPLY_LAYOUT,
        _apply_layout,
        _schema({vol.Required("layout_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_APPLY_PRESET,
        _apply_preset,
        _schema({vol.Required("preset_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_SAVE_PRESET,
        _save_preset,
        _schema(
            {
                vol.Required(CONF_NAME): cv.string,
                vol.Optional("effect_id"): cv.string,
                vol.Optional("description"): cv.string,
                vol.Optional("controls"): dict,
                vol.Optional("tags"): vol.All(cv.ensure_list, [cv.string]),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        hass,
        SERVICE_DELETE_PRESET,
        _delete_preset,
        _schema({vol.Required("preset_id"): cv.string}),
    )
    _register(
        hass,
        SERVICE_LIST_PRESETS,
        _list_presets,
        _schema({vol.Optional("effect_id"): cv.string}),
        supports_response=SupportsResponse.ONLY,
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
        SERVICE_SET_DISPLAY_FACE,
        _set_display_face,
        _schema(
            {
                vol.Required("display_id"): cv.string,
                vol.Required("effect_id"): cv.string,
                vol.Optional("controls"): dict,
                vol.Optional("blend_mode"): cv.string,
                vol.Optional("opacity"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
            }
        ),
    )
    _register(
        hass,
        SERVICE_UPLOAD_EFFECT,
        _upload_effect,
        _schema(
            {
                vol.Optional("path"): cv.string,
                vol.Optional("html"): cv.string,
                vol.Optional("file_name"): cv.string,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        hass,
        SERVICE_RUN_DIAGNOSTICS,
        _run_diagnostics,
        _schema({vol.Optional("checks"): vol.All(cv.ensure_list, [cv.string])}),
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
    if preset_id := call.data.get("preset_id"):
        await entry.runtime_data.client.apply_preset(preset_id)
        return
    effect_id = call.data.get("effect_id")
    if effect_id is None:
        raise HomeAssistantError("effect_id or preset_id is required")
    await entry.runtime_data.client.apply_effect(
        effect_id,
        controls=call.data.get("controls"),
        transition=call.data.get("transition"),
    )


async def _set_color(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    color = _color_value(call.data)
    await entry.runtime_data.client.apply_effect(
        "hypercolor:builtin:solid_color",
        controls={"color": color},
    )


async def _set_control(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.update_controls(
        {call.data["control_name"]: call.data["value"]}
    )


async def _activate_scene(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.activate_scene(call.data["scene_id"])


async def _create_scene(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    scene = await entry.runtime_data.client.create_scene(
        call.data[CONF_NAME],
        description=call.data.get("description"),
        enabled=call.data.get("enabled"),
        mutation_mode=call.data.get("mutation_mode"),
    )
    return {"scene": _jsonable(scene)}


async def _activate_profile(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.apply_profile(call.data["profile_id"])


async def _save_profile(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    profile = await entry.runtime_data.client.save_profile(
        call.data[CONF_NAME],
        description=call.data.get("description"),
        brightness=call.data.get("brightness"),
        force=bool(call.data.get("force", False)),
    )
    return {"profile": _jsonable(profile)}


async def _apply_layout(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.apply_layout(call.data["layout_id"])


async def _apply_preset(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.apply_preset(call.data["preset_id"])


async def _save_preset(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    effect_id = call.data.get("effect_id") or entry.runtime_data.coordinators["state"].data.get(
        "active_effect"
    )
    if not effect_id:
        raise HomeAssistantError("effect_id is required when no effect is active")
    preset = await entry.runtime_data.client.save_preset(
        call.data[CONF_NAME],
        effect_id,
        description=call.data.get("description"),
        controls=call.data.get("controls"),
        tags=call.data.get("tags"),
    )
    return {"preset": _jsonable(preset)}


async def _delete_preset(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.delete_preset(call.data["preset_id"])


async def _list_presets(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    presets = await entry.runtime_data.client.get_presets()
    effect_id = call.data.get("effect_id")
    if effect_id:
        presets = [preset for preset in presets if _field(preset, "effect_id") == effect_id]
    return {"presets": [_jsonable(preset) for preset in presets]}


async def _identify_device(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.identify_device(
        call.data["device_id"],
        duration_ms=call.data.get("duration_ms"),
    )


async def _set_display_face(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.client.set_display_face(
        call.data["display_id"],
        call.data["effect_id"],
        controls=call.data.get("controls"),
        blend_mode=call.data.get("blend_mode"),
        opacity=call.data.get("opacity"),
    )


async def _upload_effect(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    content = call.data.get("html")
    path = call.data.get("path")
    file_name = call.data.get("file_name")
    if content is None:
        if path is None:
            raise HomeAssistantError("path or html is required")
        effect_path = Path(path)
        content = await call.hass.async_add_executor_job(effect_path.read_bytes)
        file_name = file_name or effect_path.name
    result = await entry.runtime_data.client.upload_effect(
        file_name or "hypercolor-effect.html",
        content,
    )
    return {"effect": result}


async def _run_diagnostics(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    daemon = await runtime.client.run_diagnostics(checks=call.data.get("checks"))
    return {
        "daemon": daemon,
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


def _color_value(data: dict[str, Any]) -> str:
    if value := data.get("hex"):
        color = str(value).strip()
        return color if color.startswith("#") else f"#{color}"
    red = data.get("r")
    green = data.get("g")
    blue = data.get("b")
    if red is None or green is None or blue is None:
        raise HomeAssistantError("hex or r/g/b is required")
    return f"#{int(red):02x}{int(green):02x}{int(blue):02x}"


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__struct_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__struct_fields__}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _entry(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ConfigEntry[HypercolorRuntimeData]:
    entry_id = call.data[CONF_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"Unknown Hypercolor config entry: {entry_id}")
    return entry
