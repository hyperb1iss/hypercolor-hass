from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from websockets.exceptions import InvalidStatus

from hypercolor import HypercolorAuthenticationError, HypercolorNotFoundError
from hypercolor.websocket import EventMessage, MetricsMessage, SpectrumData

from .const import (
    CONF_AUDIO_BEAT_HOLD_MS,
    CONF_CHANNELS_AUDIO,
    CONF_CHANNELS_METRICS,
    DOMAIN,
    OPTIONS_DEFAULTS,
)
from .entity import read_field
from .repairs import (
    async_create_auth_issue,
    async_create_unavailable_issue,
    async_delete_auth_issue,
    async_delete_unavailable_issue,
)
from .runtime_data import ConnectionState, HypercolorRuntimeData

_LOGGER = logging.getLogger(__name__)

# A reconnect must not stall on a daemon that accepts the socket but is slow
# to send its hello frame (websockets only times out the handshake itself).
WS_CONNECT_TIMEOUT_S = 15

_EVENT_REFRESH_TARGETS = {
    "asset_changed": ("catalog",),
    "audio_source_changed": ("audio", "state"),
    "audio_started": ("audio", "state"),
    "audio_stopped": ("audio", "state"),
    "config_changed": ("state",),
    "control_surface_changed": ("devices",),
    "effect_started": ("catalog", "state"),
    "effect_stopped": ("catalog", "state"),
    "effect_registry_updated": ("catalog",),
    "input_source_changed": ("state",),
    "library_store_changed": ("catalog",),
    "profile_deleted": ("catalog",),
    "profile_loaded": ("state",),
    "profile_saved": ("catalog",),
    "scene_library_changed": ("catalog",),
    "scene_enabled": ("catalog",),
    "scene_settings_changed": ("catalog", "state"),
    "session_changed": ("state",),
}
_EVENT_PREFIX_REFRESH_TARGETS = (
    ("effect_", ("state",)),
    ("scene_", ("state",)),
    ("active_scene_", ("state",)),
    ("render_group_", ("state",)),
    ("layer_", ("state",)),
    ("layout_", ("catalog", "state")),
    ("device_", ("devices",)),
)


class HypercolorCoordinator(DataUpdateCoordinator[Any]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry[Any],
        name: str,
        loader: Callable[[], Awaitable[Any]],
        connection_state: ConnectionState,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}.{name}",
            update_interval=None,
            config_entry=config_entry,
        )
        self._loader = loader
        self._connection_state = connection_state
        self._config_entry = config_entry

    async def _async_update_data(self) -> Any:
        try:
            data = await self._loader()
        except HypercolorAuthenticationError as exc:
            self._connection_state.set_disconnected(exc)
            async_create_auth_issue(self.hass, self._config_entry.entry_id)
            raise ConfigEntryAuthFailed from exc
        async_delete_auth_issue(self.hass, self._config_entry.entry_id)
        return data


async def reconcile_loop(
    coordinators: list[HypercolorCoordinator],
    interval_s: int,
) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await asyncio.gather(
            *(coordinator.async_request_refresh() for coordinator in coordinators)
        )


async def load_state(client: Any) -> dict[str, Any]:
    status = await client.get_status()
    active_effect = await client.get_active_effect()
    active_scene = await client.get_active_scene()
    active_layout = await client.get_active_layout()
    active_effect_id = read_field(active_effect, "id", read_field(status, "active_effect"))
    active_effect_name = read_field(active_effect, "name", read_field(status, "active_effect"))
    active_effect_definition = None
    if active_effect_id and callable(get_effect := getattr(client, "get_effect", None)):
        with contextlib.suppress(HypercolorNotFoundError):
            active_effect_definition = await get_effect(str(active_effect_id))
    active_effect_cover_image_url = _active_effect_cover_image_url(client, active_effect)
    zones = read_field(active_scene, "groups", []) or []
    return {
        "status": status,
        "active_effect_detail": active_effect,
        "active_effect_definition": active_effect_definition,
        "active_scene_detail": active_scene,
        "active_layout_detail": active_layout,
        "active_effect": active_effect_name,
        "active_effect_id": active_effect_id,
        "active_effect_name": active_effect_name,
        "active_effect_state": read_field(active_effect, "state", "idle"),
        "active_effect_cover_image_url": active_effect_cover_image_url,
        "active_preset": read_field(active_effect, "active_preset_id"),
        "active_preset_modified": bool(read_field(active_effect, "active_preset_modified", False)),
        "active_scene": read_field(active_scene, "id"),
        "active_scene_name": read_field(active_scene, "name"),
        "active_layout": read_field(active_layout, "id"),
        "zones": list(zones),
        "groups_revision": read_field(active_scene, "groups_revision", 0),
        "global_brightness": read_field(status, "global_brightness"),
        "brightness": read_field(status, "brightness"),
        "device_count": read_field(status, "device_count"),
        "scene_count": read_field(status, "scene_count"),
        "render_loop": read_field(status, "render_loop", {}),
        "audio_available": read_field(status, "audio_available", False),
    }


async def load_catalog(client: Any) -> dict[str, Any]:
    active_effect = await _optional(client.get_active_effect)
    active_effect_id = read_field(active_effect, "id")
    return {
        "effects": await client.get_effects(),
        "scenes": await client.get_scenes(),
        "profiles": await client.get_profiles(),
        "layouts": await client.get_layouts(),
        "preset_effect_id": str(active_effect_id) if active_effect_id else None,
        "presets": (
            await client.get_effect_presets(str(active_effect_id)) if active_effect_id else []
        ),
    }


async def load_metrics(client: Any) -> dict[str, Any]:
    status = await client.get_status()
    return {
        "status": status,
        "fps": {},
        "frame_time": {},
    }


async def load_audio(client: Any) -> dict[str, Any]:
    devices = await client.get_audio_devices()
    return {"devices": devices, "spectrum": None, "enabled": True}


async def websocket_loop(runtime: HypercolorRuntimeData, options: dict[str, Any]) -> None:
    backoff_s = 1
    while True:
        stream = runtime.client.events()
        try:
            hello = await asyncio.wait_for(stream.connect(), timeout=WS_CONNECT_TIMEOUT_S)
            _mark_connected(runtime)
            _seed_hello(runtime, hello)
            channels = _websocket_channels(options)
            if channels:
                await stream.subscribe(*channels)
            await _reconcile_after_reconnect(runtime, options)
            backoff_s = 1
            async for message in stream:
                await _process_ws_message(runtime, message, options)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            error = _normalize_websocket_error(exc)
            _mark_disconnected(runtime, options, error)
            if isinstance(error, HypercolorAuthenticationError):
                _start_reauth(runtime)
            _LOGGER.debug("Hypercolor WebSocket disconnected", exc_info=True)
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 30)
        finally:
            with contextlib.suppress(Exception):
                await stream.disconnect()


async def _optional(loader: Callable[[], Awaitable[Any]]) -> Any:
    try:
        return await loader()
    except HypercolorNotFoundError:
        return None


def _active_effect_cover_image_url(client: Any, active_effect: Any) -> str | None:
    cover_image_url = read_field(active_effect, "cover_image_url")
    if not cover_image_url:
        return None
    return client.active_effect_cover_image_url()


def _seed_hello(runtime: HypercolorRuntimeData, hello: Any) -> None:
    hello_state = read_field(hello, "state")
    if not isinstance(hello_state, dict):
        return

    updates: dict[str, Any] = {}
    if (brightness := read_field(hello_state, "brightness")) is not None:
        updates.update(global_brightness=brightness, brightness=brightness)
    if (paused := read_field(hello_state, "paused")) is not None:
        updates["active_effect_state"] = "paused" if paused else "running"
    if "effect" in hello_state:
        effect = read_field(hello_state, "effect")
        updates.update(
            active_effect=read_field(effect, "name"),
            active_effect_id=read_field(effect, "id"),
        )
    if "scene" in hello_state:
        scene = read_field(hello_state, "scene")
        updates.update(
            active_scene=read_field(scene, "id"),
            active_scene_name=read_field(scene, "name"),
        )
    if (device_count := read_field(hello_state, "device_count")) is not None:
        updates["device_count"] = device_count
    if updates:
        _patch_coordinator(runtime, "state", **updates)
    if isinstance(fps := read_field(hello_state, "fps"), dict):
        _patch_coordinator(runtime, "metrics", fps=fps)


async def _reconcile_after_reconnect(
    runtime: HypercolorRuntimeData,
    options: dict[str, Any],
) -> None:
    names = ["state", "catalog", "devices"]
    if options.get(CONF_CHANNELS_METRICS, OPTIONS_DEFAULTS[CONF_CHANNELS_METRICS]):
        names.append("metrics")
    if options.get(CONF_CHANNELS_AUDIO, OPTIONS_DEFAULTS[CONF_CHANNELS_AUDIO]):
        names.append("audio")
    refreshes = [
        runtime.coordinators[name].async_request_refresh()
        for name in names
        if name in runtime.coordinators
    ]
    if refreshes:
        await asyncio.gather(*refreshes)


def _websocket_channels(options: dict[str, Any]) -> list[str]:
    channels = ["events"]
    if options.get(CONF_CHANNELS_METRICS, OPTIONS_DEFAULTS[CONF_CHANNELS_METRICS]):
        channels.append("metrics")
    if options.get(CONF_CHANNELS_AUDIO, OPTIONS_DEFAULTS[CONF_CHANNELS_AUDIO]):
        channels.append("spectrum")
    return channels


def _normalize_websocket_error(error: Exception) -> Exception:
    if isinstance(error, InvalidStatus) and error.response.status_code in {401, 403}:
        return HypercolorAuthenticationError(
            "Hypercolor WebSocket authentication failed",
            status_code=error.response.status_code,
        )
    return error


def _start_reauth(runtime: HypercolorRuntimeData) -> None:
    state = runtime.coordinators.get("state")
    if state is None:
        return
    async_create_auth_issue(state.hass, state.config_entry.entry_id)
    state.config_entry.async_start_reauth(state.hass)


def _handle_ws_message(
    runtime: HypercolorRuntimeData,
    message: Any,
    options: dict[str, Any],
) -> None:
    _mark_connected(runtime)
    if isinstance(message, MetricsMessage):
        _set_coordinator_data(
            runtime, "metrics", _normalize_metrics(read_field(message, "data", {}))
        )
    elif isinstance(message, SpectrumData):
        hold_ms = int(
            options.get(
                CONF_AUDIO_BEAT_HOLD_MS,
                OPTIONS_DEFAULTS[CONF_AUDIO_BEAT_HOLD_MS],
            )
        )
        beat_until = None
        if read_field(message, "beat", False):
            beat_until = datetime.now(UTC) + timedelta(milliseconds=hold_ms)
        current = dict(read_field(runtime.coordinators.get("audio"), "data", {}) or {})
        current["spectrum"] = {
            "level": read_field(message, "level", 0.0),
            "bass": read_field(message, "bass", 0.0),
            "mid": read_field(message, "mid", 0.0),
            "treble": read_field(message, "treble", 0.0),
            "beat": read_field(message, "beat", False),
            "beat_confidence": read_field(message, "beat_confidence", 0.0),
            "beat_until": beat_until,
        }
        _set_coordinator_data(runtime, "audio", current)
    elif isinstance(message, EventMessage):
        event = str(read_field(message, "event", ""))
        data = read_field(message, "data", {})
        _handle_event(runtime, event, data)


async def _process_ws_message(
    runtime: HypercolorRuntimeData,
    message: Any,
    options: dict[str, Any],
) -> None:
    if isinstance(message, EventMessage) and str(read_field(message, "event", "")) == (
        "resync_required"
    ):
        _mark_connected(runtime)
        await _reconcile_after_reconnect(runtime, options)
        return
    _handle_ws_message(runtime, message, options)


def _normalize_metrics(data: Any) -> dict[str, Any]:
    normalized = dict(data) if isinstance(data, dict) else {}
    normalized["fps"] = read_field(data, "fps", {}) or {}
    normalized["frame_time"] = read_field(data, "frame_time", {}) or {}
    return normalized


def _handle_event(runtime: HypercolorRuntimeData, event: str, data: Any) -> None:
    if event == "resync_required":
        _request_refresh(runtime, *sorted(runtime.coordinators))
        return
    if event == "paused":
        _patch_coordinator(runtime, "state", active_effect_state="paused")
        return
    if event == "resumed":
        _patch_coordinator(runtime, "state", active_effect_state="running")
        return
    if event == "brightness_changed":
        brightness = read_field(data, "new_value")
        if brightness is not None:
            _patch_coordinator(
                runtime,
                "state",
                global_brightness=brightness,
                brightness=brightness,
            )
        return
    if event == "fps_changed":
        current = dict(read_field(runtime.coordinators.get("metrics"), "data", {}) or {})
        fps = dict(read_field(current, "fps", {}) or {})
        fps.update(
            {
                "target": read_field(data, "new_target"),
                "actual": read_field(data, "measured"),
            }
        )
        current["fps"] = fps
        _set_coordinator_data(runtime, "metrics", current)
        return

    targets = set(_EVENT_REFRESH_TARGETS.get(event, ()))
    if not targets:
        targets.update(
            target
            for prefix, prefix_targets in _EVENT_PREFIX_REFRESH_TARGETS
            if event.startswith(prefix)
            for target in prefix_targets
        )
    if event == "config_changed" and str(read_field(data, "key", "")).startswith("audio."):
        targets.add("audio")
    if event == "library_store_changed" and read_field(data, "collection") == "presets":
        targets.add("state")
    if targets:
        _request_refresh(runtime, *sorted(targets))


def _set_coordinator_data(
    runtime: HypercolorRuntimeData,
    coordinator_name: str,
    data: Any,
) -> None:
    if coordinator := runtime.coordinators.get(coordinator_name):
        coordinator.async_set_updated_data(data)


def _patch_coordinator(
    runtime: HypercolorRuntimeData,
    coordinator_name: str,
    **updates: Any,
) -> None:
    coordinator = runtime.coordinators.get(coordinator_name)
    if coordinator is None:
        return
    current = dict(coordinator.data or {})
    current.update(updates)
    coordinator.async_set_updated_data(current)


def _request_refresh(runtime: HypercolorRuntimeData, *coordinator_names: str) -> None:
    for coordinator_name in coordinator_names:
        if coordinator := runtime.coordinators.get(coordinator_name):
            coordinator.hass.async_create_task(coordinator.async_request_refresh())


def _mark_connected(runtime: HypercolorRuntimeData) -> None:
    if not runtime.connection_state.set_connected():
        return
    if runtime.unavailable_task is not None:
        runtime.unavailable_task.cancel()
        runtime.unavailable_task = None
    state = runtime.coordinators.get("state")
    if state is not None:
        async_delete_unavailable_issue(state.hass, state.config_entry.entry_id)


def _mark_disconnected(
    runtime: HypercolorRuntimeData,
    options: dict[str, Any],
    error: BaseException,
) -> None:
    runtime.connection_state.set_disconnected(error)
    if runtime.unavailable_task is not None:
        return
    state = runtime.coordinators.get("state")
    if state is None:
        return
    unavailable_after_s = int(options.get("unavailable_after_s", 30))
    runtime.unavailable_task = state.hass.async_create_task(
        _mark_unavailable_after(runtime, unavailable_after_s),
    )


async def _mark_unavailable_after(
    runtime: HypercolorRuntimeData,
    delay_s: int,
) -> None:
    await asyncio.sleep(delay_s)
    if runtime.connection_state.connected:
        return
    state = runtime.coordinators.get("state")
    if state is None:
        return
    error = ConnectionError("Hypercolor WebSocket is disconnected")
    for coordinator in runtime.coordinators.values():
        coordinator.async_set_update_error(error)
    async_create_unavailable_issue(state.hass, state.config_entry.entry_id)
