from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from hypercolor.websocket import EventMessage, HelloMessage, MetricsMessage
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from custom_components.hypercolor.coordinator import (
    _handle_ws_message,
    _mark_disconnected,
    _normalize_websocket_error,
    _process_ws_message,
    _reconcile_after_reconnect,
    _seed_hello,
    load_catalog,
    load_state,
)
from custom_components.hypercolor.runtime_data import ConnectionState
from hypercolor import HypercolorAuthenticationError


async def test_load_state_flattens_status_and_active_resources() -> None:
    client = SimpleNamespace(
        get_status=_async_value(
            SimpleNamespace(
                active_effect="Aurora",
                global_brightness=66,
                device_count=2,
                scene_count=3,
                render_loop={"fps": 60},
                audio_available=True,
            )
        ),
        get_active_effect=_async_value(
            SimpleNamespace(
                id="aurora",
                name="Aurora",
                state="paused",
                active_preset_id="soft",
                active_preset_modified=True,
                cover_image_url="/api/v1/effects/aurora/cover",
            )
        ),
        get_active_scene=_async_value(
            SimpleNamespace(
                id="scene-1",
                name="Battlestation",
                groups=[
                    SimpleNamespace(id="zone-1", name="Desk", role="primary"),
                    SimpleNamespace(id="zone-2", name="LCD", role="display"),
                ],
                groups_revision=7,
            )
        ),
        get_active_layout=_async_value(SimpleNamespace(id="layout-1")),
        get_effect=_async_value(SimpleNamespace(presets=[])),
        active_effect_cover_image_url=lambda: (
            "http://hyperia.test:9420/api/v1/effects/active/cover"
        ),
    )

    state = await load_state(client)

    assert state["active_effect"] == "Aurora"
    assert state["active_effect_id"] == "aurora"
    assert (
        state["active_effect_cover_image_url"]
        == "http://hyperia.test:9420/api/v1/effects/active/cover"
    )
    assert state["active_preset"] == "soft"
    assert state["active_preset_modified"] is True
    assert state["active_effect_state"] == "paused"
    assert state["global_brightness"] == 66
    assert state["active_scene"] == "scene-1"
    assert state["active_scene_name"] == "Battlestation"
    assert state["active_layout"] == "layout-1"
    assert [zone.id for zone in state["zones"]] == ["zone-1", "zone-2"]
    assert state["groups_revision"] == 7


async def test_load_state_uses_client_active_cover_url() -> None:
    client = SimpleNamespace(
        get_status=_async_value(SimpleNamespace(active_effect="Aurora")),
        get_active_effect=_async_value(
            SimpleNamespace(id="aurora", name="Aurora", cover_image_url="effects/aurora/cover")
        ),
        get_active_scene=_async_value(None),
        get_active_layout=_async_value(None),
        get_effect=_async_value(SimpleNamespace(presets=[])),
        active_effect_cover_image_url=lambda: (
            "http://hyperia.test:9420/api/v1/effects/active/cover"
        ),
    )

    state = await load_state(client)

    assert (
        state["active_effect_cover_image_url"]
        == "http://hyperia.test:9420/api/v1/effects/active/cover"
    )


async def test_load_catalog_gathers_home_assistant_picker_lists() -> None:
    client = SimpleNamespace(
        get_active_effect=_async_value(SimpleNamespace(id="aurora")),
        get_effects=_async_value(["effect"]),
        get_scenes=_async_value(["scene"]),
        get_profiles=_async_value(["profile"]),
        get_layouts=_async_value(["layout"]),
        get_effect_presets=_async_effect_presets("aurora", ["preset"]),
    )

    catalog = await load_catalog(client)

    assert catalog == {
        "effects": ["effect"],
        "scenes": ["scene"],
        "profiles": ["profile"],
        "layouts": ["layout"],
        "preset_effect_id": "aurora",
        "presets": ["preset"],
    }


async def test_load_catalog_has_empty_preset_stack_without_active_effect() -> None:
    client = SimpleNamespace(
        get_active_effect=_async_value(None),
        get_effects=_async_value([]),
        get_scenes=_async_value([]),
        get_profiles=_async_value([]),
        get_layouts=_async_value([]),
    )

    catalog = await load_catalog(client)

    assert catalog["preset_effect_id"] is None
    assert catalog["presets"] == []


def test_ws_events_refresh_only_the_owning_coordinator() -> None:
    state = _FakeCoordinator({"active_effect": "Aurora"})
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={
            "state": state,
            "catalog": _FakeCoordinator({}),
            "devices": _FakeCoordinator([]),
        },
    )

    _handle_ws_message(
        runtime,
        EventMessage(event="effect_degraded", timestamp="now", data={"state": "failed"}),
        {},
    )

    assert state.data == {"active_effect": "Aurora"}
    assert state.hass.scheduled == 1
    assert runtime.coordinators["catalog"].hass.scheduled == 0
    assert runtime.coordinators["devices"].hass.scheduled == 0


def test_ws_effect_switch_refreshes_state_and_effect_scoped_presets() -> None:
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={
            "state": _FakeCoordinator({}),
            "catalog": _FakeCoordinator({}),
            "devices": _FakeCoordinator([]),
        },
    )

    _handle_ws_message(
        runtime,
        EventMessage(event="effect_started", timestamp="now", data={"effect": "Aurora"}),
        {},
    )

    assert runtime.coordinators["state"].hass.scheduled == 1
    assert runtime.coordinators["catalog"].hass.scheduled == 1
    assert runtime.coordinators["devices"].hass.scheduled == 0


def test_ws_pause_resume_and_brightness_patch_state_without_http_refresh() -> None:
    state = _FakeCoordinator({"active_effect": "Aurora", "active_effect_state": "running"})
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={"state": state},
    )

    _handle_ws_message(runtime, EventMessage(event="paused", timestamp="now", data={}), {})
    assert state.data["active_effect_state"] == "paused"

    _handle_ws_message(
        runtime,
        EventMessage(event="brightness_changed", timestamp="now", data={"new_value": 42}),
        {},
    )
    assert state.data["global_brightness"] == 42
    assert state.hass.scheduled == 0

    _handle_ws_message(runtime, EventMessage(event="resumed", timestamp="now", data={}), {})
    assert state.data["active_effect_state"] == "running"


def test_ws_resync_hint_refreshes_every_coordinator() -> None:
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={
            name: _FakeCoordinator({})
            for name in ("state", "catalog", "devices", "metrics", "audio")
        },
    )

    _handle_ws_message(
        runtime,
        EventMessage(
            event="resync_required",
            timestamp="now",
            data={"dropped_events": 17},
        ),
        {},
    )

    assert all(coordinator.hass.scheduled == 1 for coordinator in runtime.coordinators.values())


async def test_ws_resync_is_a_barrier_before_newer_events() -> None:
    release_refresh = asyncio.Event()
    refresh_started = asyncio.Event()
    state = _BarrierCoordinator(release_refresh, refresh_started)
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={"state": state},
    )
    resync = EventMessage(
        event="resync_required",
        timestamp="now",
        data={"dropped_events": 1},
    )

    barrier = asyncio.create_task(_process_ws_message(runtime, resync, {}))
    await refresh_started.wait()

    assert not barrier.done()
    release_refresh.set()
    await barrier
    await _process_ws_message(
        runtime,
        EventMessage(event="resumed", timestamp="now", data={}),
        {},
    )

    assert state.data["active_effect_state"] == "running"


def test_ws_catalog_audio_and_device_events_are_targeted() -> None:
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={
            name: _FakeCoordinator({} if name != "devices" else [])
            for name in ("state", "catalog", "devices", "audio")
        },
    )

    _handle_ws_message(
        runtime,
        EventMessage(event="library_store_changed", timestamp="now", data={}),
        {},
    )
    assert runtime.coordinators["catalog"].hass.scheduled == 1
    assert runtime.coordinators["state"].hass.scheduled == 0

    _handle_ws_message(
        runtime,
        EventMessage(event="audio_source_changed", timestamp="now", data={}),
        {},
    )
    assert runtime.coordinators["audio"].hass.scheduled == 1
    assert runtime.coordinators["state"].hass.scheduled == 1

    _handle_ws_message(
        runtime,
        EventMessage(event="device_connected", timestamp="now", data={}),
        {},
    )
    assert runtime.coordinators["devices"].hass.scheduled == 1

    _handle_ws_message(
        runtime,
        EventMessage(event="control_surface_changed", timestamp="now", data={}),
        {},
    )
    assert runtime.coordinators["devices"].hass.scheduled == 2


def test_ws_metrics_keep_nested_daemon_schema() -> None:
    metrics = _FakeCoordinator({})
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={"metrics": metrics},
    )

    _handle_ws_message(
        runtime,
        MetricsMessage(
            timestamp="now",
            data={"fps": {"actual": 58.5}, "frame_time": {"avg_ms": 4.2}},
        ),
        {},
    )

    assert metrics.data["fps"]["actual"] == 58.5
    assert metrics.data["frame_time"]["avg_ms"] == 4.2


def test_ws_preset_library_event_refreshes_catalog_and_state() -> None:
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: False),
        coordinators={
            "state": _FakeCoordinator({}),
            "catalog": _FakeCoordinator({}),
        },
    )

    _handle_ws_message(
        runtime,
        EventMessage(
            event="library_store_changed",
            timestamp="now",
            data={"collection": "presets", "kind": "updated"},
        ),
        {},
    )

    assert runtime.coordinators["catalog"].hass.scheduled == 1
    assert runtime.coordinators["state"].hass.scheduled == 1


def test_ws_hello_patches_canonical_state_and_metrics_fields() -> None:
    state = _FakeCoordinator(
        {"active_effect": "Old", "active_effect_id": "old", "active_effect_state": "running"}
    )
    metrics = _FakeCoordinator({})
    runtime: Any = SimpleNamespace(coordinators={"state": state, "metrics": metrics})

    _seed_hello(
        runtime,
        HelloMessage(
            version="1",
            state={
                "paused": True,
                "brightness": 42,
                "effect": {"id": "aurora", "name": "Aurora"},
                "scene": {"id": "scene-1", "name": "Desk"},
                "device_count": 3,
                "fps": {"actual": 58.5, "target": 60},
            },
            capabilities=[],
            subscriptions=[],
        ),
    )

    assert state.data["active_effect_state"] == "paused"
    assert state.data["global_brightness"] == 42
    assert state.data["active_effect_id"] == "aurora"
    assert state.data["active_scene"] == "scene-1"
    assert state.data["device_count"] == 3
    assert metrics.data["fps"]["actual"] == 58.5


def test_ws_rejected_handshake_is_typed_as_authentication_failure() -> None:
    response = Response(401, "Unauthorized", Headers())

    error = _normalize_websocket_error(InvalidStatus(response))

    assert isinstance(error, HypercolorAuthenticationError)
    assert error.status_code == 401


async def test_websocket_disconnect_marks_all_coordinators_unavailable_after_threshold(
    monkeypatch: Any,
) -> None:
    created_issues: list[str] = []
    monkeypatch.setattr(
        "custom_components.hypercolor.coordinator.async_create_unavailable_issue",
        lambda _hass, entry_id: created_issues.append(entry_id),
    )
    hass = SimpleNamespace(async_create_task=asyncio.create_task)
    state: Any = _FakeCoordinator({})
    state.hass = hass
    state.config_entry = SimpleNamespace(entry_id="entry-1")
    catalog = _FakeCoordinator({})
    runtime: Any = SimpleNamespace(
        connection_state=ConnectionState(connected=True),
        coordinators={"state": state, "catalog": catalog},
        unavailable_task=None,
    )

    _mark_disconnected(runtime, {"unavailable_after_s": 0}, ConnectionError("offline"))
    await runtime.unavailable_task

    assert isinstance(state.update_error, ConnectionError)
    assert isinstance(catalog.update_error, ConnectionError)
    assert created_issues == ["entry-1"]


async def test_reconnect_reconciliation_does_not_swallow_refresh_failures() -> None:
    coordinator = _RetryCoordinator()
    runtime: Any = SimpleNamespace(coordinators={"state": coordinator})

    with pytest.raises(ConnectionError, match="retry me"):
        await _reconcile_after_reconnect(runtime, {})
    await _reconcile_after_reconnect(runtime, {})

    assert coordinator.calls == 2


def _async_value(value: object):
    async def _loader(*_args: object) -> object:
        return value

    return _loader


def _async_effect_presets(expected_effect_id: str, value: object):
    async def _loader(effect_id: str) -> object:
        assert effect_id == expected_effect_id
        return value

    return _loader


class _FakeHass:
    def __init__(self) -> None:
        self.scheduled = 0

    def async_create_task(self, coro: Any) -> None:
        self.scheduled += 1
        coro.close()


class _FakeCoordinator:
    def __init__(self, data: Any) -> None:
        self.data: Any = data
        self.hass = _FakeHass()
        self.update_error: BaseException | None = None

    async def async_request_refresh(self) -> None:
        return None

    def async_set_updated_data(self, data: Any) -> None:
        self.data = data

    def async_set_update_error(self, error: BaseException) -> None:
        self.update_error = error


class _BarrierCoordinator(_FakeCoordinator):
    def __init__(self, release_refresh: asyncio.Event, refresh_started: asyncio.Event) -> None:
        super().__init__({"active_effect_state": "running"})
        self._release_refresh = release_refresh
        self._refresh_started = refresh_started

    async def async_request_refresh(self) -> None:
        self._refresh_started.set()
        await self._release_refresh.wait()
        self.data = {"active_effect_state": "paused"}


class _RetryCoordinator:
    def __init__(self) -> None:
        self.calls = 0

    async def async_request_refresh(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("retry me")
