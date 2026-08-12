from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.hypercolor.const import DOMAIN
from custom_components.hypercolor.services import CONF_CONFIG_ENTRY_ID, SERVICE_SET_COLOR
from tests.support.hass import first_state, setup_entry
from tests.support.hypercolor_daemon import FakeHypercolorDaemon

pytest_plugins = ("tests.support.fixtures",)


async def test_config_entry_boots_and_controls_fake_daemon(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)

    master = first_state(hass, "light", lambda state: state.attributes.get("effect") == "Rainbow")
    assert master.state == "on"
    assert master.attributes["active_effect_id"] == "rainbow"
    assert (
        master.attributes["active_effect_cover_image_url"]
        == f"http://127.0.0.1:{fake_daemon.port}/api/v1/effects/active/cover"
    )
    assert (
        master.attributes["effect_image"]
        == f"http://127.0.0.1:{fake_daemon.port}/api/v1/effects/active/cover"
    )
    assert "Solid Color" in master.attributes["effect_list"]

    assert master.attributes["effect_description"] == "Test rainbow"
    assert master.attributes["effect_publisher"] == "Hypercolor"
    assert master.attributes["effect_audio_reactive"] is False
    assert master.attributes["effect_tags"] == ["test"]
    assert master.attributes["effect_category"] == "ambient"
    controls_by_id = {control["id"]: control for control in master.attributes["effect_controls"]}
    assert {"speed", "brightness"} <= set(controls_by_id)
    assert controls_by_id["speed"]["kind"] == "number"

    preset_select = first_state(
        hass,
        "select",
        lambda state: state.entity_id.endswith("_preset"),
    )
    assert preset_select.attributes["options"] == ["Rainbow Soft"]
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": preset_select.entity_id, "option": "Rainbow Soft"},
        blocking=True,
    )
    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "rainbow",
        "controls": {"speed": 60},
        "preset_id": "preset-rainbow",
    }

    speed = first_state(hass, "number", lambda state: "speed" in state.entity_id)
    assert float(speed.state) == 60.0

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": speed.entity_id, "value": 35},
        blocking=True,
    )

    assert fake_daemon.control_updates[-1] == {"speed": 35.0}
    preset_select = hass.states.get(preset_select.entity_id)
    assert preset_select is not None
    assert preset_select.state == "Rainbow Soft"
    assert preset_select.attributes["active_preset_modified"] is True

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": master.entity_id, "effect": "Solid Color"},
        blocking=True,
    )

    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "solid_color",
        "controls": {},
    }

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_COLOR,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            "hex": "#80ff00",
        },
        blocking=True,
    )

    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "solid_color",
        "controls": {"color": "#80ff00"},
    }

    zone = first_state(
        hass, "light", lambda state: state.attributes.get("zone_id") == "zone-primary"
    )
    assert zone.state == "on"
    assert zone.attributes["role"] == "primary"
    assert zone.attributes["scene_id"] == "default"
    assert zone.attributes["output_count"] == 1

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": zone.entity_id, "brightness": 128, "effect": "Rainbow"},
        blocking=True,
    )

    assert fake_daemon.zone_updates[-1] == {
        "scene_id": "default",
        "zone_id": "zone-primary",
        "brightness": 0.502,
    }
    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "rainbow",
        "controls": {},
        "render_group": "zone-primary",
    }

    await hass.services.async_call(
        "light",
        "turn_off",
        {"entity_id": zone.entity_id},
        blocking=True,
    )

    assert fake_daemon.zone_updates[-1] == {
        "scene_id": "default",
        "zone_id": "zone-primary",
        "enabled": False,
    }
    assert await hass.config_entries.async_unload(entry.entry_id)
