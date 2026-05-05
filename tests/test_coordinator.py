from __future__ import annotations

from types import SimpleNamespace

from custom_components.hypercolor.coordinator import load_catalog, load_state


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
        get_active_effect=_async_value(SimpleNamespace(id="aurora", active_preset_id="soft")),
        get_active_scene=_async_value(SimpleNamespace(id="scene-1")),
        get_active_layout=_async_value(SimpleNamespace(id="layout-1")),
    )

    state = await load_state(client)

    assert state["active_effect"] == "aurora"
    assert state["global_brightness"] == 66
    assert state["active_scene"] == "scene-1"
    assert state["active_layout"] == "layout-1"


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


def _async_value(value: object):
    async def _loader() -> object:
        return value

    return _loader
