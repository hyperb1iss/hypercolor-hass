from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.hypercolor.const import DOMAIN
from custom_components.hypercolor.services import CONF_CONFIG_ENTRY_ID, SERVICE_SET_COLOR
from tests.support.hass import first_state, setup_entry
from tests.support.hypercolor_daemon import FakeHypercolorDaemon
from tests.support.hypercolor_payloads import PRIMARY_LAYER_ID, PRIMARY_ZONE_ID

pytest_plugins = ("tests.support.fixtures",)


async def test_master_light_and_presets_drive_the_fake_daemon(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)

    master = first_state(hass, "light", lambda state: state.attributes.get("effect") == "Rainbow")
    assert master.state == "on"
    assert master.attributes["active_effect_id"] == "rainbow"
    cover_url = f"http://127.0.0.1:{fake_daemon.port}/api/v1/effects/rainbow/cover"
    assert master.attributes["active_effect_cover_image_url"] == cover_url
    assert master.attributes["effect_image"] == cover_url
    assert "Solid Color" in master.attributes["effect_list"]
    assert master.attributes["active_scene_id"] == "default"
    assert master.attributes["zone_count"] == 1
    scene_select = first_state(hass, "select", lambda state: state.entity_id.endswith("_scene"))
    assert scene_select.state == "unknown"
    assert scene_select.attributes["options"] == ["Evening"]

    assert master.attributes["effect_description"] == "Test rainbow"
    assert master.attributes["effect_publisher"] == "Hypercolor"
    assert master.attributes["effect_audio_reactive"] is False
    assert master.attributes["effect_tags"] == ["test"]
    assert master.attributes["effect_category"] == "ambient"
    controls_by_id = {control["id"]: control for control in master.attributes["effect_controls"]}
    assert {"speed", "brightness"} <= set(controls_by_id)
    assert controls_by_id["speed"]["kind"] == "number"
    assert controls_by_id["speed"]["value"] == 60.0

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
        "controls": {"speed": 60.0},
        "preset_id": "preset-rainbow",
        "zone": PRIMARY_ZONE_ID,
    }

    speed = first_state(hass, "number", lambda state: "speed" in state.entity_id)
    assert float(speed.state) == 60.0

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": speed.entity_id, "value": 35},
        blocking=True,
    )

    assert fake_daemon.control_updates[-1] == {
        "zone": PRIMARY_ZONE_ID,
        "layer": PRIMARY_LAYER_ID,
        "values": {"speed": 35.0},
    }
    speed = hass.states.get(speed.entity_id)
    assert speed is not None
    assert float(speed.state) == 35.0
    preset_select = hass.states.get(preset_select.entity_id)
    assert preset_select is not None
    assert preset_select.state == "Rainbow Soft"

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

    applied = fake_daemon.applied_effects[-1]
    assert applied["effect_id"] == "solid_color"
    assert applied["controls"]["color"]["kind"] == "color_linear"
    assert applied["controls"]["color"]["value"]["g"] == 1.0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_zone_light_patches_the_live_zone(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    fake_daemon.active_effect_id = "solid_color"
    entry = await setup_entry(hass, port=fake_daemon.port)

    zone = first_state(
        hass, "light", lambda state: state.attributes.get("zone_id") == PRIMARY_ZONE_ID
    )
    assert zone.state == "on"
    assert zone.attributes["role"] == "primary"
    assert zone.attributes["scene_id"] == "default"
    assert zone.attributes["effect_id"] == "solid_color"
    assert zone.attributes["layer_count"] == 1
    assert zone.attributes["member_count"] == 1

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": zone.entity_id, "brightness": 128, "effect": "Rainbow"},
        blocking=True,
    )

    assert fake_daemon.zone_updates[-1] == {
        "zone_id": PRIMARY_ZONE_ID,
        "brightness": 0.502,
    }
    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "rainbow",
        "controls": {},
        "zone": PRIMARY_ZONE_ID,
    }

    await hass.services.async_call(
        "light",
        "turn_off",
        {"entity_id": zone.entity_id},
        blocking=True,
    )

    assert fake_daemon.zone_updates[-1] == {
        "zone_id": PRIMARY_ZONE_ID,
        "enabled": False,
    }
    zone = hass.states.get(zone.entity_id)
    assert zone is not None
    assert zone.state == "off"
    assert await hass.config_entries.async_unload(entry.entry_id)
