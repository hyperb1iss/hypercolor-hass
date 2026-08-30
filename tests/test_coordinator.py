from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from hypercolor.websocket import EventMessage, MetricsMessage, SpectrumData
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from custom_components.hypercolor import coordinator as coordinator_module
from custom_components.hypercolor.coordinator import (
    HypercolorCoordinator,
    _mark_disconnected,
    _normalize_websocket_error,
    _process_ws_message,
    _websocket_channels,
    event_requires_refresh,
    load_catalog,
    load_snapshot,
    load_state,
)
from custom_components.hypercolor.models import HypercolorSnapshot
from custom_components.hypercolor.runtime_data import (
    ConnectionSource,
    ConnectionState,
)
from hypercolor import HypercolorAuthenticationError, HypercolorConnectionError
from hypercolor.models import (
    AudioDevicesResponse,
    DeviceSummary,
    EffectDetailResponse,
    EffectPresetSummary,
    EffectSummary,
    LayoutSummary,
    OutputResource,
    SceneDocument,
    SceneSummary,
    SpatialLayout,
    SystemStatus,
)
from tests.support import hypercolor_payloads as payloads
from tests.support.hypercolor_payloads import PRIMARY_LAYER_ID, PRIMARY_ZONE_ID
from tests.support.wire import minimal


async def test_load_state_reads_the_live_scene_tree() -> None:
    client = SnapshotClientFixture()

    state = await load_state(client)

    assert state.active_effect_id == "aurora"
    assert state.active_effect_name == "Aurora"
    assert state.active_preset_id == "soft"
    assert state.active_effect is not None
    assert state.active_effect.zone_id == PRIMARY_ZONE_ID
    assert state.active_effect.layer_id == PRIMARY_LAYER_ID
    assert state.scene.id == "scene-1"
    assert state.active_layout is not None
    assert state.active_layout.id == "layout-1"
    assert state.brightness == 0.66
    assert state.paused is False
    assert state.active_effect_cover_image_url is not None
    assert state.active_effect_cover_image_url.endswith("/effects/aurora/cover")
    assert client.max_in_flight == 4
    assert client.effect_lookups == ["aurora"]


async def test_load_state_never_uses_display_name_as_effect_id() -> None:
    client = SnapshotClientFixture(with_active_effect=False)

    state = await load_state(client)

    assert state.active_effect_id is None
    assert state.active_effect_name == "Aurora"
    assert state.active_effect_cover_image_url is None
    assert client.effect_lookups == []


async def test_load_catalog_builds_unique_picker_indexes_concurrently() -> None:
    client = SnapshotClientFixture()
    client.effects = [
        _effect("aurora-v1", "Aurora"),
        _effect("aurora-v2", "Aurora"),
    ]
    client.presets = [
        _preset("soft-bundled", "Soft", origin="bundled"),
        _preset("soft-saved", "Soft", origin="saved"),
    ]

    catalog = await load_catalog(client)

    assert catalog.effects.options == ["Aurora (aurora-v1)", "Aurora (aurora-v2)"]
    assert catalog.effects.resolve("Aurora (aurora-v2)") == "aurora-v2"
    assert catalog.preset_effect_id == "aurora"
    assert catalog.presets.options == ["Soft (Built-in)", "Soft (Saved)"]
    assert client.max_in_flight == 4


async def test_snapshot_hides_preset_stack_from_a_newer_effect() -> None:
    client = SnapshotClientFixture()
    state = await load_state(client)
    client.scene = _scene("rainbow", preset_id=None)
    client.presets = []

    catalog = await load_catalog(client)
    snapshot = HypercolorSnapshot(state=state, catalog=catalog, devices=())

    assert catalog.preset_effect_id == "rainbow"
    assert state.active_effect_id == "aurora"
    assert snapshot.active_effect_presets.items == ()


async def test_rest_refresh_preserves_websocket_telemetry() -> None:
    client = SnapshotClientFixture()
    initial = await load_snapshot(client, load_audio=True)
    spectrum = _spectrum()
    streamed = initial.with_metrics({"fps": {"actual": 59.8}}).with_spectrum(
        spectrum,
        42.0,
    )

    refreshed = await load_snapshot(client, load_audio=True, previous=streamed)

    assert refreshed.metrics == {"fps": {"actual": 59.8}}
    assert refreshed.audio.devices == client.audio_devices
    assert refreshed.audio.spectrum is spectrum
    assert refreshed.audio.beat_until == 42.0


def test_event_refresh_filter_covers_state_bearing_daemon_taxonomy() -> None:
    for event in (
        "device_error",
        "effect_degraded",
        "control_surface_changed",
        "scene_enabled",
        "zone_changed",
        "layer_stack_changed",
        "active_scene_changed",
        "audio_source_changed",
        "asset_changed",
        "brightness_changed",
        "paused",
        "config_changed",
    ):
        assert event_requires_refresh(event) is True

    for event in (
        "audio_level_update",
        "beat_detected",
        "fps_changed",
        "frame_rendered",
        "input_event_received",
        "profile_loaded",
        "future_unknown",
    ):
        assert event_requires_refresh(event) is False


def test_websocket_channels_intersect_daemon_capabilities() -> None:
    options = {"channels.metrics": True, "channels.audio": True}

    assert _websocket_channels(options, capabilities={"events", "metrics"}) == [
        "events",
        "metrics",
    ]


async def test_ws_resync_is_a_barrier_before_newer_state() -> None:
    order: list[str] = []

    async def prior_refresh() -> None:
        await asyncio.sleep(0)
        order.append("prior")

    class Coordinator:
        async def async_request_refresh(self) -> None:
            order.append("resync")

    task = asyncio.create_task(prior_refresh())
    runtime: Any = SimpleNamespace(
        coordinator=Coordinator(),
        refresh_tasks={task},
    )

    await _process_ws_message(
        runtime,
        EventMessage(event="resync_required", timestamp="", data={}),
        {},
    )

    assert order == ["prior", "resync"]


def test_ws_rejected_handshake_is_typed_as_authentication_failure() -> None:
    response = Response(401, "Unauthorized", Headers(), b"")
    error = _normalize_websocket_error(InvalidStatus(response))

    assert isinstance(error, HypercolorAuthenticationError)


async def test_websocket_disconnect_creates_unavailable_issue_after_threshold(
    monkeypatch,
) -> None:
    created_issues: list[str] = []
    monkeypatch.setattr(
        coordinator_module,
        "async_create_unavailable_issue",
        lambda _hass, entry_id: created_issues.append(entry_id),
    )
    monkeypatch.setattr(
        coordinator_module,
        "async_delete_unavailable_issue",
        lambda _hass, _entry_id: None,
    )
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_connected(ConnectionSource.WEBSOCKET)
    coordinator = _repair_coordinator(state, unavailable_after_s=0)
    runtime: Any = SimpleNamespace(connection_state=state, coordinator=coordinator)

    _mark_disconnected(runtime, ConnectionError("offline"))

    assert state.is_available(0) is False
    assert created_issues == ["entry-1"]


async def test_sdk_failure_waits_for_shared_unavailable_deadline(monkeypatch) -> None:
    created_issues: list[str] = []
    monkeypatch.setattr(
        coordinator_module,
        "async_create_unavailable_issue",
        lambda _hass, entry_id: created_issues.append(entry_id),
    )
    monkeypatch.setattr(
        coordinator_module,
        "async_delete_unavailable_issue",
        lambda _hass, _entry_id: None,
    )
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    coordinator = _repair_coordinator(state, unavailable_after_s=30)

    async def fail(_previous: HypercolorSnapshot | None) -> HypercolorSnapshot:
        raise HypercolorConnectionError("offline")

    coordinator._loader = fail
    cast(Any, coordinator).data = None

    with pytest.raises(UpdateFailed, match="Failed to refresh Hypercolor snapshot"):
        await coordinator._async_update_data()

    assert state.is_available(30) is True
    assert created_issues == []
    assert coordinator.unavailable_task is not None

    unavailable_task = coordinator.unavailable_task
    coordinator.mark_connected(ConnectionSource.SNAPSHOT)
    await asyncio.gather(unavailable_task, return_exceptions=True)

    assert coordinator.unavailable_task is None
    assert created_issues == []


async def test_unexpected_loader_bug_does_not_poison_connection_health() -> None:
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    coordinator = _repair_coordinator(state, unavailable_after_s=30)

    async def fail(_previous: HypercolorSnapshot | None) -> HypercolorSnapshot:
        raise TypeError("integration bug")

    coordinator._loader = fail
    cast(Any, coordinator).data = None

    with pytest.raises(TypeError, match="integration bug"):
        await coordinator._async_update_data()

    assert state.is_source_connected(ConnectionSource.SNAPSHOT) is True
    assert coordinator.unavailable_task is None


def test_healthy_push_does_not_resync_repair_registry(monkeypatch) -> None:
    deleted_issues: list[str] = []
    monkeypatch.setattr(
        coordinator_module,
        "async_delete_unavailable_issue",
        lambda _hass, entry_id: deleted_issues.append(entry_id),
    )
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    coordinator = _repair_coordinator(state, unavailable_after_s=30)

    coordinator.mark_connected(ConnectionSource.WEBSOCKET)
    coordinator.mark_connected(ConnectionSource.WEBSOCKET)

    assert deleted_issues == ["entry-1"]


async def test_websocket_messages_preserve_typed_push_telemetry(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        coordinator_module,
        "async_delete_unavailable_issue",
        lambda _hass, _entry_id: None,
    )
    coordinator = _PushCoordinator(await load_snapshot(SnapshotClientFixture(), load_audio=True))
    runtime: Any = _PushRuntime(coordinator)

    await _process_ws_message(
        runtime,
        MetricsMessage(
            timestamp="2026-08-12T00:00:00Z",
            data={
                "fps": {"actual": 59.8},
                "frame_time": {"avg_ms": 16.7},
                "queue_depth": 2,
            },
        ),
        {},
    )
    spectrum = _spectrum()
    await _process_ws_message(runtime, spectrum, {"audio_beat_hold_ms": 200})
    await _process_ws_message(
        runtime,
        EventMessage(event="effect_started", timestamp="", data={}),
        {},
    )
    await coordinator.refreshed.wait()

    assert coordinator.data.metrics == {
        "fps": {"actual": 59.8},
        "frame_time": {"avg_ms": 16.7},
        "queue_depth": 2,
    }
    assert coordinator.data.audio.spectrum is spectrum
    assert coordinator.data.audio.beat_until is not None
    assert runtime.connection_state.is_source_connected(ConnectionSource.WEBSOCKET)
    assert coordinator.refreshes == 1


class SnapshotClientFixture:
    def __init__(self, *, with_active_effect: bool = True) -> None:
        self.status = SystemStatus.from_dict(
            payloads.system_status(active_effect="Aurora", brightness=66, paused=False)
        )
        self.output = OutputResource.from_dict({"power": "running", "brightness": 0.66})
        self.scene = _scene("aurora" if with_active_effect else "", preset_id="soft")
        self.active_layout = SpatialLayout.from_dict(
            minimal(
                SpatialLayout,
                id="layout-1",
                name="Desk",
                canvas_width=640,
                canvas_height=480,
                version=1,
            )
        )
        self.effects = [_effect("aurora", "Aurora")]
        self.scenes = [SceneSummary.from_dict(minimal(SceneSummary, id="scene-1", name="Desk"))]
        self.layouts = [
            LayoutSummary.from_dict(
                minimal(
                    LayoutSummary,
                    id="layout-1",
                    name="Desk",
                    canvas_width=640,
                    canvas_height=480,
                    zone_count=1,
                )
            )
        ]
        self.presets = [_preset("soft", "Soft", origin="bundled")]
        self.audio_devices = AudioDevicesResponse.from_dict({"current": "none", "devices": []})
        self.effect_lookups: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def get_status(self) -> SystemStatus:
        return await self._load(self.status)

    async def get_output(self) -> OutputResource:
        return await self._load(self.output)

    async def get_live_scene(self) -> SceneDocument:
        return await self._load(self.scene)

    async def get_active_layout(self) -> SpatialLayout | None:
        return await self._load(self.active_layout)

    async def get_effect(self, effect_id: str) -> EffectDetailResponse:
        self.effect_lookups.append(effect_id)
        detail = payloads.effect_detail(effect_id)
        detail["name"] = effect_id.title()
        return await self._load(EffectDetailResponse.from_dict(detail))

    async def get_effects(self) -> list[EffectSummary]:
        return await self._load(self.effects)

    async def get_scenes(self) -> list[SceneSummary]:
        return await self._load(self.scenes)

    async def get_layouts(self) -> list[LayoutSummary]:
        return await self._load(self.layouts)

    async def get_effect_presets(self, effect_id: str) -> list[EffectPresetSummary]:
        return await self._load(self.presets)

    async def get_devices(self) -> list[DeviceSummary]:
        return await self._load([])

    async def get_audio_devices(self) -> AudioDevicesResponse:
        return await self._load(self.audio_devices)

    def effect_cover_image_url(self, effect_id: str) -> str:
        return f"http://hyperia.test:9420/api/v1/effects/{effect_id}/cover"

    async def _load[ValueT](self, value: ValueT) -> ValueT:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return value


class _PushCoordinator:
    def __init__(self, data: HypercolorSnapshot) -> None:
        self.data = data
        self.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        self.config_entry = SimpleNamespace(entry_id="entry-1", options={})
        self.refreshed = asyncio.Event()
        self.refreshes = 0
        self.connection_state = ConnectionState()

    def async_set_updated_data(self, data: HypercolorSnapshot) -> None:
        self.data = data

    async def async_request_refresh(self) -> None:
        self.refreshes += 1
        self.refreshed.set()

    def mark_connected(self, source: ConnectionSource) -> None:
        self.connection_state.set_connected(source)


class _PushRuntime:
    def __init__(self, coordinator: _PushCoordinator) -> None:
        self.coordinator = coordinator
        self.connection_state = coordinator.connection_state
        self.refresh_tasks: set[asyncio.Task[None]] = set()

    @property
    def snapshot(self) -> HypercolorSnapshot:
        return self.coordinator.data


def _repair_coordinator(
    state: ConnectionState,
    *,
    unavailable_after_s: int,
) -> HypercolorCoordinator:
    coordinator = object.__new__(HypercolorCoordinator)
    coordinator.hass = SimpleNamespace(async_create_task=asyncio.create_task)
    coordinator.config_entry = SimpleNamespace(
        entry_id="entry-1",
        options={"unavailable_after_s": unavailable_after_s},
    )
    coordinator._connection_state = state
    coordinator.unavailable_task = None
    return coordinator


def _scene(effect_id: str, *, preset_id: str | None) -> SceneDocument:
    document = payloads.scene_document(
        [payloads.zone(effect_id, {"speed": 72.0}, preset_id)],
    )
    document["id"] = "scene-1"
    document["name"] = "Battlestation"
    return SceneDocument.from_dict(document)


def _effect(effect_id: str, name: str) -> EffectSummary:
    return EffectSummary.from_dict(
        minimal(
            EffectSummary,
            id=effect_id,
            name=name,
            description="Cascading neon",
            author="Aurora Labs",
            category="ambient",
            source="html",
            runnable=True,
            version="1.2.0",
            audio_reactive=True,
            tags=["cyberpunk", "rain"],
        )
    )


def _preset(preset_id: str, name: str, *, origin: str) -> EffectPresetSummary:
    return EffectPresetSummary.from_dict(
        minimal(
            EffectPresetSummary,
            id=preset_id,
            name=name,
            effect_id="aurora",
            origin=origin,
            editable=origin == "saved",
            controls={},
        )
    )


def _spectrum() -> SpectrumData:
    return SpectrumData(
        timestamp_ms=123,
        bin_count=2,
        level=0.8,
        bass=0.7,
        mid=0.4,
        treble=0.2,
        beat=True,
        beat_confidence=0.9,
        bins=[0.7, 0.2],
    )
