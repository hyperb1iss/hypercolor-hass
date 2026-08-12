from __future__ import annotations

import os
import stat
from collections.abc import Callable, Coroutine
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, selector, service as service_helper

from .const import DOMAIN
from .runtime_data import HypercolorRuntimeData

CONF_CONFIG_ENTRY_ID = "config_entry_id"

SERVICE_APPLY_EFFECT = "apply_effect"
SERVICE_SET_COLOR = "set_color"
SERVICE_SET_CONTROL = "set_control"
SERVICE_ACTIVATE_SCENE = "activate_scene"
SERVICE_DEACTIVATE_SCENE = "deactivate_scene"
SERVICE_CREATE_SCENE = "create_scene"
SERVICE_SET_ZONE = "set_zone"
SERVICE_LIST_ZONES = "list_zones"
SERVICE_SET_UNASSIGNED_BEHAVIOR = "set_unassigned_behavior"
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

_MAX_EFFECT_SIZE_BYTES = 1024 * 1024


def async_setup_services(hass: HomeAssistant) -> None:
    _register(
        hass,
        SERVICE_APPLY_EFFECT,
        _apply_effect,
        _schema(
            {
                vol.Required("effect_id"): cv.string,
                vol.Optional("controls"): dict,
                vol.Optional("transition"): dict,
                vol.Optional("preset_id"): cv.string,
                vol.Optional("zone_id"): cv.string,
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
        SERVICE_DEACTIVATE_SCENE,
        _deactivate_scene,
        _schema({}),
    )
    _register(
        hass,
        SERVICE_SET_ZONE,
        _set_zone,
        _schema(
            {
                vol.Required("zone_id"): cv.string,
                vol.Optional("scene_id"): cv.string,
                vol.Optional(CONF_NAME): cv.string,
                vol.Optional("brightness"): vol.All(int, vol.Range(min=0, max=100)),
                vol.Optional("enabled"): bool,
                vol.Optional("make_primary"): bool,
            }
        ),
    )
    _register(
        hass,
        SERVICE_LIST_ZONES,
        _list_zones,
        _schema({vol.Optional("scene_id"): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
    _register(
        hass,
        SERVICE_SET_UNASSIGNED_BEHAVIOR,
        _set_unassigned_behavior,
        _schema(
            {
                vol.Required("behavior"): vol.In(["off", "hold", "fallback"]),
                vol.Optional("fallback_zone_id"): cv.string,
                vol.Optional("scene_id"): cv.string,
            }
        ),
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
        _schema(
            {
                vol.Required("effect_id"): cv.string,
                vol.Required("preset_id"): cv.string,
            }
        ),
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
    service_helper.async_register_admin_service(
        hass,
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
    runtime = entry.runtime_data
    zone_id = call.data.get("zone_id")
    await runtime.async_mutate(
        lambda: runtime.client.apply_effect(
            call.data["effect_id"],
            controls=call.data.get("controls"),
            transition=call.data.get("transition"),
            preset_id=call.data.get("preset_id"),
            render_group=zone_id,
        )
    )


async def _set_color(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    color = _color_value(call.data)
    runtime = entry.runtime_data
    await runtime.async_mutate(
        lambda: runtime.client.apply_effect(
            "solid_color",
            controls={"color": color},
        )
    )


async def _set_control(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(
        lambda: runtime.client.update_controls({call.data["control_name"]: call.data["value"]})
    )


async def _activate_scene(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(lambda: runtime.client.activate_scene(call.data["scene_id"]))


async def _deactivate_scene(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    await entry.runtime_data.async_mutate(entry.runtime_data.client.deactivate_scene)


async def _set_zone(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    scene_id = await _resolve_scene_id(entry, call.data.get("scene_id"))
    name = call.data.get(CONF_NAME)
    brightness_value = call.data.get("brightness")
    brightness = round(int(brightness_value) / 100, 4) if brightness_value is not None else None
    enabled = call.data.get("enabled")
    make_primary = bool(call.data.get("make_primary")) or None
    if name is None and brightness is None and enabled is None and make_primary is None:
        raise HomeAssistantError("set_zone needs at least one field to change")
    await runtime.async_mutate(
        lambda: runtime.client.update_zone(
            scene_id,
            call.data["zone_id"],
            name=name,
            brightness=brightness,
            enabled=enabled,
            make_primary=make_primary,
        )
    )


async def _list_zones(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    client = entry.runtime_data.client
    scene_id = await _resolve_scene_id(entry, call.data.get("scene_id"))
    result = await client.get_zones(scene_id)
    return {
        "scene_id": scene_id,
        "groups_revision": result.groups_revision,
        "zones": [_jsonable(zone) for zone in result.items],
    }


async def _set_unassigned_behavior(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    client = entry.runtime_data.client
    scene_id = await _resolve_scene_id(entry, call.data.get("scene_id"))
    behavior: str | dict[str, Any] = call.data["behavior"]
    if behavior == "fallback":
        fallback_zone_id = call.data.get("fallback_zone_id")
        if not fallback_zone_id:
            raise HomeAssistantError("fallback behavior requires fallback_zone_id")
        behavior = {"fallback": fallback_zone_id}
    await entry.runtime_data.async_mutate(
        lambda: client.set_unassigned_behavior(scene_id, behavior)
    )


async def _resolve_scene_id(
    entry: ConfigEntry[HypercolorRuntimeData],
    scene_id: str | None,
) -> str:
    if scene_id:
        return scene_id
    active = entry.runtime_data.snapshot.state.active_scene
    if active is None:
        raise HomeAssistantError("No active Hypercolor scene")
    return active.id


async def _create_scene(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    scene = await runtime.async_mutate(
        lambda: runtime.client.create_scene(
            call.data[CONF_NAME],
            description=call.data.get("description"),
            enabled=call.data.get("enabled"),
            mutation_mode=call.data.get("mutation_mode"),
        )
    )
    return {"scene": _jsonable(scene)}


async def _activate_profile(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(lambda: runtime.client.apply_profile(call.data["profile_id"]))


async def _save_profile(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    profile = await runtime.async_mutate(
        lambda: runtime.client.save_profile(
            call.data[CONF_NAME],
            description=call.data.get("description"),
            brightness=call.data.get("brightness"),
            force=bool(call.data.get("force", False)),
        )
    )
    return {"profile": _jsonable(profile)}


async def _apply_layout(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(lambda: runtime.client.apply_layout(call.data["layout_id"]))


async def _apply_preset(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(
        lambda: runtime.client.apply_effect_preset(
            call.data["effect_id"],
            call.data["preset_id"],
        )
    )


async def _save_preset(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    effect_id = call.data.get("effect_id") or runtime.snapshot.state.active_effect_id
    if not effect_id:
        raise HomeAssistantError("effect_id is required when no effect is active")
    preset = await runtime.async_mutate(
        lambda: runtime.client.save_preset(
            call.data[CONF_NAME],
            effect_id,
            description=call.data.get("description"),
            controls=call.data.get("controls"),
            tags=call.data.get("tags"),
        )
    )
    return {"preset": _jsonable(preset)}


async def _delete_preset(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(lambda: runtime.client.delete_preset(call.data["preset_id"]))


async def _list_presets(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    effect_id = call.data.get("effect_id") or runtime.snapshot.state.active_effect_id
    if not effect_id:
        raise HomeAssistantError("effect_id is required when no effect is active")
    presets = await runtime.client.get_effect_presets(effect_id)
    return {"presets": [_jsonable(preset) for preset in presets]}


async def _identify_device(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(
        lambda: runtime.client.identify_device(
            call.data["device_id"],
            duration_ms=call.data.get("duration_ms"),
        )
    )


async def _set_display_face(call: ServiceCall) -> None:
    entry = _entry(call.hass, call)
    runtime = entry.runtime_data
    await runtime.async_mutate(
        lambda: runtime.client.set_display_face(
            call.data["display_id"],
            call.data["effect_id"],
            controls=call.data.get("controls"),
            blend_mode=call.data.get("blend_mode"),
            opacity=call.data.get("opacity"),
        )
    )


async def _upload_effect(call: ServiceCall) -> dict[str, Any]:
    entry = _entry(call.hass, call)
    content = call.data.get("html")
    path = call.data.get("path")
    file_name = call.data.get("file_name")
    if content is None:
        if path is None:
            raise HomeAssistantError("path or html is required")
        try:
            effect_path = await call.hass.async_add_executor_job(
                partial(Path(path).resolve, strict=True)
            )
        except OSError as exc:
            raise HomeAssistantError(f"Unable to read effect file: {exc}") from exc
        if not call.hass.config.is_allowed_path(str(effect_path)):
            raise HomeAssistantError("Effect path is outside Home Assistant's allowed paths")
        try:
            content = await call.hass.async_add_executor_job(_read_limited_effect, effect_path)
        except HomeAssistantError:
            raise
        except OSError as exc:
            raise HomeAssistantError(f"Unable to read effect file: {exc}") from exc
        file_name = file_name or effect_path.name
    content_size = len(content.encode()) if isinstance(content, str) else len(content)
    if content_size > _MAX_EFFECT_SIZE_BYTES:
        raise HomeAssistantError("Effect content exceeds the 1 MiB upload limit")
    runtime = entry.runtime_data
    result = await runtime.async_mutate(
        lambda: runtime.client.upload_effect(
            file_name or "hypercolor-effect.html",
            content,
        )
    )
    return {"effect": result}


def _read_limited_effect(effect_path: Path) -> bytes:
    before_open = effect_path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before_open.st_mode):
        raise HomeAssistantError("Effect path must reference a regular file")
    if before_open.st_size > _MAX_EFFECT_SIZE_BYTES:
        raise HomeAssistantError("Effect file exceeds the 1 MiB upload limit")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(effect_path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise HomeAssistantError("Effect path must reference a regular file")
        if (opened.st_dev, opened.st_ino) != (before_open.st_dev, before_open.st_ino):
            raise HomeAssistantError("Effect file changed while it was being opened")
        if opened.st_size > _MAX_EFFECT_SIZE_BYTES:
            raise HomeAssistantError("Effect file exceeds the 1 MiB upload limit")
        with os.fdopen(descriptor, "rb", closefd=False) as effect_file:
            return effect_file.read(_MAX_EFFECT_SIZE_BYTES + 1)
    finally:
        os.close(descriptor)


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
        "snapshot_coordinator": runtime.coordinator.last_update_success,
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


def _entry(
    hass: HomeAssistant,
    call: ServiceCall,
) -> ConfigEntry[HypercolorRuntimeData]:
    entry_id = call.data[CONF_CONFIG_ENTRY_ID]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"Unknown Hypercolor config entry: {entry_id}")
    return entry
