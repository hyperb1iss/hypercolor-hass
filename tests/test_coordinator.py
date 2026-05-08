from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from custom_components.hypercolor.coordinator import _handle_ws_message, load_catalog, load_state


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
                active_preset_id="soft",
                cover_image_url="/api/v1/effects/aurora/cover",
            )
        ),
        get_active_scene=_async_value(SimpleNamespace(id="scene-1")),
        get_active_layout=_async_value(SimpleNamespace(id="layout-1")),
        root_url="http://hyperia.test:9420",
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
    assert state["global_brightness"] == 66
    assert state["active_scene"] == "scene-1"
    assert state["active_layout"] == "layout-1"


async def test_load_state_resolves_cover_image_without_client_helper() -> None:
    client = SimpleNamespace(
        get_status=_async_value(SimpleNamespace(active_effect="Aurora")),
        get_active_effect=_async_value(
            SimpleNamespace(id="aurora", name="Aurora", cover_image_url="effects/aurora/cover")
        ),
        get_active_scene=_async_value(None),
        get_active_layout=_async_value(None),
        root_url="http://hyperia.test:9420/api/v1",
    )

    state = await load_state(client)

    assert (
        state["active_effect_cover_image_url"]
        == "http://hyperia.test:9420/api/v1/effects/aurora/cover"
    )


async def test_load_catalog_gathers_home_assistant_picker_lists() -> None:
    client = SimpleNamespace(
        get_effects=_async_value(["effect"]),
        get_scenes=_async_value(["scene"]),
        get_profiles=_async_value(["profile"]),
        get_layouts=_async_value(["layout"]),
        get_presets=_async_value(["preset"]),
    )

    catalog = await load_catalog(client)

    assert catalog == {
        "effects": ["effect"],
        "scenes": ["scene"],
        "profiles": ["profile"],
        "layouts": ["layout"],
        "presets": ["preset"],
    }


def test_ws_events_schedule_refresh_without_overwriting_state() -> None:
    state = _FakeCoordinator({"active_effect": "Aurora"})
    runtime: Any = SimpleNamespace(
        connection_state=SimpleNamespace(set_connected=lambda: None),
        coordinators={
            "state": state,
            "catalog": _FakeCoordinator({}),
            "devices": _FakeCoordinator([]),
        },
    )

    _handle_ws_message(
        runtime,
        EventMessage("effect_degraded", {"state": "failed"}),
        {},
    )

    assert state.data == {"active_effect": "Aurora"}
    assert state.hass.scheduled == 1
    assert runtime.coordinators["catalog"].hass.scheduled == 1
    assert runtime.coordinators["devices"].hass.scheduled == 1


def _async_value(value: object):
    async def _loader() -> object:
        return value

    return _loader


class EventMessage:
    def __init__(self, event: str, data: object) -> None:
        self.event = event
        self.data = data


class _FakeHass:
    def __init__(self) -> None:
        self.scheduled = 0

    def async_create_task(self, coro: Any) -> None:
        self.scheduled += 1
        coro.close()


class _FakeCoordinator:
    def __init__(self, data: object) -> None:
        self.data = data
        self.hass = _FakeHass()

    async def async_request_refresh(self) -> None:
        return None
