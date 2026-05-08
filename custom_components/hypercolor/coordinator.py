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

from hypercolor import HypercolorAuthenticationError, HypercolorNotFoundError

from .const import (
    CONF_AUDIO_BEAT_HOLD_MS,
    CONF_CHANNELS_AUDIO,
    CONF_CHANNELS_DEVICE_METRICS,
    CONF_CHANNELS_METRICS,
    DOMAIN,
    OPTIONS_DEFAULTS,
)
from .entity import read_field
from .repairs import (
    async_create_auth_issue,
    async_create_unavailable_issue,
    async_delete_runtime_issues,
)
from .runtime_data import ConnectionState, HypercolorRuntimeData

_LOGGER = logging.getLogger(__name__)


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
        except Exception as exc:
            self._connection_state.set_disconnected(exc)
            async_create_unavailable_issue(self.hass, self._config_entry.entry_id)
            raise
        self._connection_state.set_connected()
        async_delete_runtime_issues(self.hass, self._config_entry.entry_id)
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
    active_effect = await _optional(client.get_active_effect)
    active_scene = await _optional(client.get_active_scene)
    active_layout = await _optional(client.get_active_layout)
    active_effect_id = read_field(active_effect, "id", read_field(status, "active_effect"))
    active_effect_name = read_field(active_effect, "name", read_field(status, "active_effect"))
    active_effect_cover_image_url = _active_effect_cover_image_url(client, active_effect)
    return {
        "status": status,
        "active_effect_detail": active_effect,
        "active_scene_detail": active_scene,
        "active_layout_detail": active_layout,
        "active_effect": active_effect_name,
        "active_effect_id": active_effect_id,
        "active_effect_name": active_effect_name,
        "active_effect_cover_image_url": active_effect_cover_image_url,
        "active_preset": read_field(active_effect, "active_preset_id"),
        "active_scene": read_field(active_scene, "id"),
        "active_layout": read_field(active_layout, "id"),
        "global_brightness": read_field(status, "global_brightness"),
        "brightness": read_field(status, "brightness"),
        "device_count": read_field(status, "device_count"),
        "scene_count": read_field(status, "scene_count"),
        "render_loop": read_field(status, "render_loop", {}),
        "audio_available": read_field(status, "audio_available", False),
    }


async def load_catalog(client: Any) -> dict[str, Any]:
    return {
        "effects": await client.get_effects(),
        "scenes": await client.get_scenes(),
        "profiles": await client.get_profiles(),
        "layouts": await client.get_layouts(),
        "presets": await client.get_presets(),
    }


async def load_metrics(client: Any) -> dict[str, Any]:
    status = await client.get_status()
    return {
        "status": status,
        "render_loop": read_field(status, "render_loop", {}),
    }


async def load_audio(client: Any) -> dict[str, Any]:
    devices = await client.get_audio_devices()
    return {"devices": devices, "spectrum": None, "enabled": True}


async def websocket_loop(runtime: HypercolorRuntimeData, options: dict[str, Any]) -> None:
    backoff_s = 1
    while True:
        stream = runtime.client.events()
        try:
            hello = await stream.connect()
            runtime.connection_state.set_connected()
            _seed_hello(runtime, hello)
            await _reconcile_after_reconnect(runtime)
            channels = _websocket_channels(options)
            if channels:
                await stream.subscribe(*channels)
            backoff_s = 1
            async for message in stream:
                _handle_ws_message(runtime, message, options)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            runtime.connection_state.set_disconnected(exc)
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
    if active_cover_url := _client_active_effect_cover_image_url(client):
        return active_cover_url
    return _daemon_url(client, str(cover_image_url))


def _client_active_effect_cover_image_url(client: Any) -> str | None:
    loader = getattr(client, "active_effect_cover_image_url", None)
    if not callable(loader):
        return None
    value = loader()
    return str(value) if value else None


def _daemon_url(client: Any, path: str) -> str | None:
    if path.startswith(("http://", "https://")):
        return path
    root_url = getattr(client, "root_url", None)
    if not isinstance(root_url, str) or not root_url:
        return None
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{root_url.rstrip('/')}{normalized_path}"


def _seed_hello(runtime: HypercolorRuntimeData, hello: Any) -> None:
    state = read_field(hello, "state")
    if isinstance(state, dict) and (coordinator := runtime.coordinators.get("state")):
        merged = dict(coordinator.data or {})
        merged.update(state)
        coordinator.async_set_updated_data(merged)


async def _reconcile_after_reconnect(runtime: HypercolorRuntimeData) -> None:
    refreshes = [
        runtime.coordinators[name].async_request_refresh()
        for name in ("state", "catalog", "devices")
        if name in runtime.coordinators
    ]
    if refreshes:
        await asyncio.gather(*refreshes, return_exceptions=True)


def _websocket_channels(options: dict[str, Any]) -> list[str]:
    channels = ["events"]
    if options.get(CONF_CHANNELS_METRICS, OPTIONS_DEFAULTS[CONF_CHANNELS_METRICS]):
        channels.append("metrics")
    if options.get(
        CONF_CHANNELS_DEVICE_METRICS,
        OPTIONS_DEFAULTS[CONF_CHANNELS_DEVICE_METRICS],
    ):
        channels.append("device_metrics")
    if options.get(CONF_CHANNELS_AUDIO, OPTIONS_DEFAULTS[CONF_CHANNELS_AUDIO]):
        channels.append("spectrum")
    return channels


def _handle_ws_message(
    runtime: HypercolorRuntimeData,
    message: Any,
    options: dict[str, Any],
) -> None:
    runtime.connection_state.set_connected()
    message_name = type(message).__name__
    if message_name == "MetricsMessage":
        _set_coordinator_data(runtime, "metrics", read_field(message, "data", {}))
    elif message_name == "SpectrumData":
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
    elif message_name == "EventMessage":
        event = str(read_field(message, "event", ""))
        if event.startswith(("effect", "scene", "profile", "layout", "device")):
            _request_refresh(runtime, "state", "catalog", "devices")


def _set_coordinator_data(
    runtime: HypercolorRuntimeData,
    coordinator_name: str,
    data: Any,
) -> None:
    if coordinator := runtime.coordinators.get(coordinator_name):
        coordinator.async_set_updated_data(data)


def _request_refresh(runtime: HypercolorRuntimeData, *coordinator_names: str) -> None:
    for coordinator_name in coordinator_names:
        if coordinator := runtime.coordinators.get(coordinator_name):
            coordinator.hass.async_create_task(coordinator.async_request_refresh())
