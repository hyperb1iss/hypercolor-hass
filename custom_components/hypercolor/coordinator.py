from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from websockets.exceptions import InvalidStatus

from hypercolor import HypercolorAuthenticationError
from hypercolor.models import (
    ActiveEffect,
    ActiveScene,
    AudioDevices,
    Device,
    EffectPreset,
    EffectSummary,
    Layout,
    LayoutSummary,
    ProfileSummary,
    Scene,
    SystemState,
)
from hypercolor.websocket import EventMessage, MetricsMessage, SpectrumData

from .const import (
    CONF_AUDIO_BEAT_HOLD_MS,
    CONF_CHANNELS_AUDIO,
    CONF_CHANNELS_METRICS,
    DOMAIN,
    OPTIONS_DEFAULTS,
)
from .models import HypercolorAudio, HypercolorCatalog, HypercolorSnapshot, HypercolorState
from .repairs import (
    async_create_auth_issue,
    async_create_unavailable_issue,
    async_delete_auth_issue,
    async_delete_unavailable_issue,
)
from .runtime_data import ConnectionSource, ConnectionState, HypercolorRuntimeData

_LOGGER = logging.getLogger(__name__)

WS_CONNECT_TIMEOUT_S = 15

_REFRESH_EVENTS = {
    "active_scene_changed",
    "brightness_changed",
    "effect_activated",
    "effect_changed",
    "effect_control_changed",
    "effect_deactivated",
    "effect_error",
    "effect_layer_added",
    "effect_layer_removed",
    "effect_started",
    "effect_stopped",
    "paused",
    "render_group_changed",
    "resumed",
    "session_changed",
    "effect_registry_updated",
    "layout_changed",
    "layout_deleted",
    "layout_saved",
    "library_store_changed",
    "profile_changed",
    "profile_deleted",
    "profile_saved",
    "scene_library_changed",
    "scene_settings_changed",
    "device_connected",
    "device_disconnected",
    "device_discovered",
    "device_discovery_completed",
    "device_state_changed",
}


class SnapshotClient(Protocol):
    async def get_status(self) -> SystemState: ...

    async def get_active_effect(self) -> ActiveEffect | None: ...

    async def get_active_scene(self) -> ActiveScene | None: ...

    async def get_active_layout(self) -> Layout | None: ...

    async def get_effects(self) -> list[EffectSummary]: ...

    async def get_scenes(self) -> list[Scene]: ...

    async def get_profiles(self) -> list[ProfileSummary]: ...

    async def get_layouts(self) -> list[LayoutSummary]: ...

    async def get_effect_presets(self, effect_id: str) -> list[EffectPreset]: ...

    async def get_devices(self) -> list[Device]: ...

    async def get_audio_devices(self) -> AudioDevices: ...

    def active_effect_cover_image_url(self) -> str: ...


class HypercolorCoordinator(DataUpdateCoordinator[HypercolorSnapshot]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry[Any],
        loader: Callable[[HypercolorSnapshot | None], Awaitable[HypercolorSnapshot]],
        connection_state: ConnectionState,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}.snapshot",
            update_interval=None,
            config_entry=config_entry,
        )
        self._loader = loader
        self._connection_state = connection_state
        self.config_entry: ConfigEntry[Any] = config_entry

    async def _async_update_data(self) -> HypercolorSnapshot:
        try:
            data = await self._loader(self.data)
        except HypercolorAuthenticationError as exc:
            self._connection_state.set_disconnected(ConnectionSource.SNAPSHOT, exc)
            async_create_auth_issue(self.hass, self.config_entry.entry_id)
            raise ConfigEntryAuthFailed from exc
        except Exception as exc:
            self._connection_state.set_disconnected(ConnectionSource.SNAPSHOT, exc)
            async_create_unavailable_issue(self.hass, self.config_entry.entry_id)
            raise
        if self.data is not None:
            data = data.with_push_telemetry(self.data)
        self._connection_state.set_connected(ConnectionSource.SNAPSHOT)
        async_delete_auth_issue(self.hass, self.config_entry.entry_id)
        async_delete_unavailable_issue(self.hass, self.config_entry.entry_id)
        return data


async def reconcile_loop(coordinator: HypercolorCoordinator, interval_s: int) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await coordinator.async_request_refresh()


async def load_snapshot(
    client: SnapshotClient,
    *,
    load_audio: bool,
    previous: HypercolorSnapshot | None = None,
) -> HypercolorSnapshot:
    active_effect_task = asyncio.create_task(client.get_active_effect())
    state_task = load_state(client, active_effect=active_effect_task)
    catalog_task = load_catalog(client, active_effect=active_effect_task)
    devices_task = client.get_devices()
    audio_task = client.get_audio_devices() if load_audio else _empty_audio()
    state, catalog, devices, audio_devices = await asyncio.gather(
        state_task,
        catalog_task,
        devices_task,
        audio_task,
    )
    previous_audio = previous.audio if previous is not None else HypercolorAudio()
    return HypercolorSnapshot(
        state=state,
        catalog=catalog,
        devices=tuple(devices),
        metrics=previous.metrics if previous is not None else {},
        audio=HypercolorAudio(
            devices=audio_devices,
            spectrum=previous_audio.spectrum,
            beat_until=previous_audio.beat_until,
        ),
    )


async def load_state(
    client: SnapshotClient,
    *,
    active_effect: Awaitable[ActiveEffect | None] | None = None,
) -> HypercolorState:
    active_effect_request = (
        active_effect if active_effect is not None else client.get_active_effect()
    )
    status, active_effect_value, active_scene, active_layout = await asyncio.gather(
        client.get_status(),
        active_effect_request,
        client.get_active_scene(),
        client.get_active_layout(),
    )
    cover_image_url = (
        client.active_effect_cover_image_url()
        if active_effect_value is not None and active_effect_value.cover_image_url
        else None
    )
    return HypercolorState(
        status=status,
        active_effect=active_effect_value,
        active_scene=active_scene,
        active_layout=active_layout,
        active_effect_cover_image_url=cover_image_url,
    )


async def load_catalog(
    client: SnapshotClient,
    *,
    active_effect: Awaitable[ActiveEffect | None] | None = None,
) -> HypercolorCatalog:
    active_effect_request = (
        active_effect if active_effect is not None else client.get_active_effect()
    )
    effects, scenes, profiles, layouts, preset_stack = await asyncio.gather(
        client.get_effects(),
        client.get_scenes(),
        client.get_profiles(),
        client.get_layouts(),
        _load_effect_presets(client, active_effect_request),
    )
    preset_effect_id, presets = preset_stack
    return HypercolorCatalog.build(
        effects=effects,
        scenes=scenes,
        profiles=profiles,
        layouts=layouts,
        preset_effect_id=preset_effect_id,
        presets=presets,
    )


async def _load_effect_presets(
    client: SnapshotClient,
    active_effect: Awaitable[ActiveEffect | None],
) -> tuple[str | None, list[EffectPreset]]:
    effect = await active_effect
    if effect is None:
        return None, []
    return effect.id, await client.get_effect_presets(effect.id)


async def websocket_loop(runtime: HypercolorRuntimeData, options: dict[str, Any]) -> None:
    backoff_s = 1
    while True:
        stream = runtime.client.events()
        try:
            hello = await asyncio.wait_for(stream.connect(), timeout=WS_CONNECT_TIMEOUT_S)
            _mark_connected(runtime)
            channels = _websocket_channels(options, capabilities=set(hello.capabilities))
            if channels:
                await stream.subscribe(*channels)
            await runtime.coordinator.async_request_refresh()
            backoff_s = 1
            async for message in stream:
                await _process_ws_message(runtime, message, options)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            error = _normalize_websocket_error(exc)
            _mark_disconnected(runtime, options, error)
            if isinstance(error, HypercolorAuthenticationError):
                entry = runtime.coordinator.config_entry
                async_create_auth_issue(runtime.coordinator.hass, entry.entry_id)
                entry.async_start_reauth(runtime.coordinator.hass)
            _LOGGER.debug("Hypercolor WebSocket disconnected", exc_info=True)
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 30)
        finally:
            with contextlib.suppress(Exception):
                await stream.disconnect()


def _websocket_channels(
    options: dict[str, Any],
    *,
    capabilities: set[str] | None = None,
) -> list[str]:
    channels = ["events"]
    if options.get(CONF_CHANNELS_METRICS, OPTIONS_DEFAULTS[CONF_CHANNELS_METRICS]):
        channels.append("metrics")
    if options.get(CONF_CHANNELS_AUDIO, OPTIONS_DEFAULTS[CONF_CHANNELS_AUDIO]):
        channels.append("spectrum")
    if capabilities is None:
        return channels
    return [channel for channel in channels if channel in capabilities]


def _normalize_websocket_error(error: Exception) -> Exception:
    if isinstance(error, InvalidStatus) and error.response.status_code in {401, 403}:
        return HypercolorAuthenticationError(
            "Hypercolor WebSocket authentication failed",
            status_code=error.response.status_code,
        )
    return error


async def _process_ws_message(
    runtime: HypercolorRuntimeData,
    message: object,
    options: dict[str, Any],
) -> None:
    if isinstance(message, EventMessage) and message.event == "resync_required":
        if runtime.refresh_tasks:
            await asyncio.gather(*tuple(runtime.refresh_tasks), return_exceptions=True)
        await runtime.coordinator.async_request_refresh()
        return
    _handle_ws_message(runtime, message, options)


def _handle_ws_message(
    runtime: HypercolorRuntimeData,
    message: object,
    options: dict[str, Any],
) -> None:
    _mark_connected(runtime)
    if isinstance(message, MetricsMessage):
        runtime.coordinator.async_set_updated_data(
            runtime.snapshot.with_metrics(_normalize_metrics(message.data))
        )
        return
    if isinstance(message, SpectrumData):
        hold_ms = int(
            options.get(CONF_AUDIO_BEAT_HOLD_MS, OPTIONS_DEFAULTS[CONF_AUDIO_BEAT_HOLD_MS])
        )
        beat_until = monotonic() + hold_ms / 1000 if message.beat else None
        runtime.coordinator.async_set_updated_data(
            runtime.snapshot.with_spectrum(message, beat_until)
        )
        return
    if not isinstance(message, EventMessage):
        return
    if event_requires_refresh(message.event):
        _request_refresh(runtime)


def event_requires_refresh(event: str) -> bool:
    return event in _REFRESH_EVENTS


def _request_refresh(runtime: HypercolorRuntimeData) -> None:
    task = runtime.coordinator.hass.async_create_task(
        runtime.coordinator.async_request_refresh(),
    )
    runtime.refresh_tasks.add(task)
    task.add_done_callback(runtime.refresh_tasks.discard)


def _normalize_metrics(data: Any) -> dict[str, Any]:
    normalized = dict(data) if isinstance(data, dict) else {}
    normalized["fps"] = data.get("fps", {}) if isinstance(data, dict) else {}
    normalized["frame_time"] = data.get("frame_time", {}) if isinstance(data, dict) else {}
    return normalized


def _mark_connected(runtime: HypercolorRuntimeData) -> None:
    runtime.connection_state.set_connected(ConnectionSource.WEBSOCKET)
    if runtime.unavailable_task is not None:
        runtime.unavailable_task.cancel()
        runtime.unavailable_task = None
    entry = runtime.coordinator.config_entry
    async_delete_unavailable_issue(runtime.coordinator.hass, entry.entry_id)


def _mark_disconnected(
    runtime: HypercolorRuntimeData,
    options: dict[str, Any],
    error: BaseException,
) -> None:
    runtime.connection_state.set_disconnected(ConnectionSource.WEBSOCKET, error)
    if runtime.unavailable_task is not None:
        return
    unavailable_after_s = int(options.get("unavailable_after_s", 30))
    runtime.unavailable_task = runtime.coordinator.hass.async_create_task(
        _mark_unavailable_after(runtime, unavailable_after_s)
    )


async def _mark_unavailable_after(
    runtime: HypercolorRuntimeData,
    delay_s: int,
) -> None:
    await asyncio.sleep(delay_s)
    if runtime.connection_state.is_source_connected(ConnectionSource.WEBSOCKET):
        return
    error = ConnectionError("Hypercolor WebSocket is disconnected")
    runtime.coordinator.async_set_update_error(error)
    entry = runtime.coordinator.config_entry
    async_create_unavailable_issue(runtime.coordinator.hass, entry.entry_id)


async def _empty_audio() -> AudioDevices | None:
    return None
