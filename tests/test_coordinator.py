from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from hypercolor.models.system import RenderLoopStatus
from hypercolor.websocket import EventMessage, MetricsMessage, SpectrumData
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from custom_components.hypercolor import coordinator as coordinator_module
from custom_components.hypercolor.coordinator import (
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
from hypercolor import HypercolorAuthenticationError
from hypercolor.models import (
    ActiveEffect,
    ActiveScene,
    AudioDevices,
    Device,
    EffectPreset,
    EffectPresetOrigin,
    EffectSummary,
    LayoutSummary,
    ProfileSummary,
    Scene,
    ServerIdentity,
    SpatialLayout,
    SystemState,
)


async def test_load_state_joins_active_resources_concurrently() -> None:
    client = SnapshotClientFixture()

    state = await load_state(client)

    assert state.active_effect_id == "aurora"
    assert state.active_effect_name == "Aurora"
    assert state.active_preset_id == "soft"
    assert state.active_scene is not None
    assert state.active_scene.id == "scene-1"
    assert state.active_layout is not None
    assert state.active_layout.id == "layout-1"
    assert state.active_effect_cover_image_url is not None
    assert state.active_effect_cover_image_url.endswith("/effects/active/cover")
    assert client.max_in_flight == 4


async def test_load_state_never_uses_display_name_as_effect_id() -> None:
    client = SnapshotClientFixture(with_active_effect=False)

    state = await load_state(client)

    assert state.active_effect_id is None
    assert state.active_effect_name == "Aurora"
    assert state.active_effect_cover_image_url is None


async def test_load_catalog_builds_unique_picker_indexes_concurrently() -> None:
    client = SnapshotClientFixture()
    client.effects = [
        _effect("aurora-v1", "Aurora"),
        _effect("aurora-v2", "Aurora"),
    ]
    client.presets = [
        EffectPreset(
            id="soft-bundled",
            name="Soft",
            effect_id="aurora",
            origin=EffectPresetOrigin.BUNDLED,
            editable=False,
        ),
        EffectPreset(
            id="soft-saved",
            name="Soft",
            effect_id="aurora",
            origin=EffectPresetOrigin.SAVED,
            editable=True,
        ),
    ]

    catalog = await load_catalog(client)

    assert catalog.effects.options == ["Aurora (aurora-v1)", "Aurora (aurora-v2)"]
    assert catalog.effects.resolve("Aurora (aurora-v2)") == "aurora-v2"
    assert catalog.preset_effect_id == "aurora"
    assert catalog.presets.options == ["Soft (Built-in)", "Soft (Saved)"]
    assert client.max_in_flight == 5


async def test_snapshot_hides_preset_stack_from_a_newer_effect() -> None:
    client = SnapshotClientFixture()
    state = await load_state(client)
    client.active_effect = ActiveEffect(id="rainbow", name="Rainbow", state="running")
    client.presets = []

    catalog = await load_catalog(client)
    snapshot = HypercolorSnapshot(state=state, catalog=catalog, devices=())

    assert catalog.preset_effect_id == "rainbow"
    assert state.active_effect_id == "aurora"
    assert snapshot.active_effect_presets.items == ()


async def test_rest_refresh_preserves_websocket_telemetry() -> None:
    client = SnapshotClientFixture()
    initial = await load_snapshot(client, load_audio=True)
    spectrum = SpectrumData(
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
    streamed = initial.with_metrics({"fps": {"actual": 59.8}}).with_spectrum(
        spectrum,
        42.0,
    )

    refreshed = await load_snapshot(client, load_audio=True, previous=streamed)

    assert refreshed.metrics == {"fps": {"actual": 59.8}}
    assert refreshed.audio.devices == client.audio_devices
    assert refreshed.audio.spectrum is spectrum
    assert refreshed.audio.beat_until == 42.0


def test_event_refresh_filter_is_exact() -> None:
    assert event_requires_refresh("effect_started") is True
    assert event_requires_refresh("effect_registry_updated") is True
    assert event_requires_refresh("device_connected") is True
    assert event_requires_refresh("device_metrics") is False
    assert event_requires_refresh("device_future_unknown") is False


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
    state = ConnectionState()
    state.set_connected(ConnectionSource.SNAPSHOT)
    state.set_connected(ConnectionSource.WEBSOCKET)
    coordinator = _UnavailableCoordinator()
    runtime: Any = SimpleNamespace(
        connection_state=state,
        coordinator=coordinator,
        unavailable_task=None,
    )

    _mark_disconnected(runtime, {"unavailable_after_s": 0}, ConnectionError("offline"))
    await runtime.unavailable_task

    assert state.is_available(0) is False
    assert created_issues == ["entry-1"]


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
    spectrum = SpectrumData(
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
        self.status = _status()
        self.active_effect = (
            ActiveEffect(
                id="aurora",
                name="Aurora",
                state="running",
                active_preset_id="soft",
                cover_image_url="/api/v1/effects/aurora/cover",
            )
            if with_active_effect
            else None
        )
        self.active_scene = ActiveScene(id="scene-1", name="Battlestation")
        self.active_layout = SpatialLayout(
            id="layout-1",
            name="Desk",
            canvas_width=640,
            canvas_height=480,
        )
        self.effects = [_effect("aurora", "Aurora")]
        self.scenes = [Scene(id="scene-1", name="Battlestation")]
        self.profiles = [ProfileSummary(id="profile-1", name="Default")]
        self.layouts = [
            LayoutSummary(id="layout-1", name="Desk", canvas_width=640, canvas_height=480)
        ]
        self.presets = [
            EffectPreset(
                id="soft",
                name="Soft",
                effect_id="aurora",
                origin=EffectPresetOrigin.BUNDLED,
                editable=False,
            )
        ]
        self.audio_devices = AudioDevices(current="none")
        self.in_flight = 0
        self.max_in_flight = 0

    async def get_status(self) -> SystemState:
        return await self._load(self.status)

    async def get_active_effect(self) -> ActiveEffect | None:
        return await self._load(self.active_effect)

    async def get_active_scene(self) -> ActiveScene | None:
        return await self._load(self.active_scene)

    async def get_active_layout(self) -> SpatialLayout | None:
        return await self._load(self.active_layout)

    async def get_effects(self) -> list[EffectSummary]:
        return await self._load(self.effects)

    async def get_scenes(self) -> list[Scene]:
        return await self._load(self.scenes)

    async def get_profiles(self) -> list[ProfileSummary]:
        return await self._load(self.profiles)

    async def get_layouts(self) -> list[LayoutSummary]:
        return await self._load(self.layouts)

    async def get_effect_presets(self, effect_id: str) -> list[EffectPreset]:
        assert self.active_effect is not None
        assert effect_id == self.active_effect.id
        return await self._load(self.presets)

    async def get_devices(self) -> list[Device]:
        return await self._load([])

    async def get_audio_devices(self) -> AudioDevices:
        return await self._load(self.audio_devices)

    def active_effect_cover_image_url(self) -> str:
        return "http://hyperia.test:9420/api/v1/effects/active/cover"

    async def _load[ValueT](self, value: ValueT) -> ValueT:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return value


class _UnavailableCoordinator:
    def __init__(self) -> None:
        self.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        self.config_entry = SimpleNamespace(entry_id="entry-1", options={})


class _PushCoordinator:
    def __init__(self, data: HypercolorSnapshot) -> None:
        self.data = data
        self.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        self.config_entry = SimpleNamespace(entry_id="entry-1", options={})
        self.refreshed = asyncio.Event()
        self.refreshes = 0

    def async_set_updated_data(self, data: HypercolorSnapshot) -> None:
        self.data = data

    async def async_request_refresh(self) -> None:
        self.refreshes += 1
        self.refreshed.set()


class _PushRuntime:
    def __init__(self, coordinator: _PushCoordinator) -> None:
        self.coordinator = coordinator
        self.connection_state = ConnectionState()
        self.unavailable_task = None
        self.refresh_tasks: set[asyncio.Task[None]] = set()

    @property
    def snapshot(self) -> HypercolorSnapshot:
        return self.coordinator.data


def _status() -> SystemState:
    return SystemState(
        running=True,
        version="0.3.1",
        server=ServerIdentity(instance_id="srv-1", instance_name="Hyperia", version="0.3.1"),
        config_path="/config",
        data_dir="/data",
        cache_dir="/cache",
        uptime_seconds=12,
        device_count=2,
        effect_count=3,
        scene_count=1,
        global_brightness=66,
        audio_available=True,
        capture_available=False,
        render_loop=RenderLoopStatus(state="running", fps_tier="full", total_frames=10),
        event_bus_subscribers=1,
        active_effect="Aurora",
    )


def _effect(effect_id: str, name: str) -> EffectSummary:
    return EffectSummary(
        id=effect_id,
        name=name,
        description="Cascading neon",
        author="Aurora Labs",
        category="ambient",
        source="builtin",
        runnable=True,
        version="1.2.0",
        audio_reactive=True,
        tags=["cyberpunk", "rain"],
    )
