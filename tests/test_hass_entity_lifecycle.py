from __future__ import annotations

from dataclasses import replace

import pytest
from homeassistant.components.light import LightEntityFeature
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.hypercolor.const import (
    CONF_API_KEY,
    CONF_RECONCILE_INTERVAL_S,
    CONF_UNAVAILABLE_AFTER_S,
    DOMAIN,
)
from hypercolor.models import SceneDocument
from tests.support.hass import activate_entry, first_state, setup_entry
from tests.support.hypercolor_daemon import FakeHypercolorDaemon
from tests.support.hypercolor_payloads import PRIMARY_ZONE_ID, scene_document

pytest_plugins = ("tests.support.fixtures",)


@pytest.mark.parametrize("absent", [True, False], ids=["absent-zone", "disconnected-daemon"])
async def test_unavailable_zone_publishes_presence_and_light_capabilities(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
    absent: bool,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port, setup=False)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_UNAVAILABLE_AFTER_S: 0}
    )
    await activate_entry(hass, entry)
    try:
        runtime = entry.runtime_data
        original = runtime.snapshot
        zone = first_state(
            hass, "light", lambda state: state.attributes.get("zone_id") == PRIMARY_ZONE_ID
        )
        if absent:
            runtime.coordinator.async_set_updated_data(
                replace(
                    original,
                    state=replace(
                        original.state, scene=SceneDocument.from_dict(scene_document([]))
                    ),
                )
            )
        else:
            for source in runtime.connection_state.sources:
                runtime.connection_state.set_disconnected(
                    source, ConnectionError("daemon offline")
                )
        await hass.async_block_till_done()

        unavailable = hass.states.get(zone.entity_id)
        assert unavailable is not None
        assert unavailable.state == "unavailable"
        assert unavailable.attributes["zone_id"] == PRIMARY_ZONE_ID
        assert unavailable.attributes["role"] == (None if absent else "primary")
        assert unavailable.attributes["supported_color_modes"] == ["brightness"]
        assert unavailable.attributes["supported_features"] == LightEntityFeature.EFFECT

        if absent:
            runtime.coordinator.async_set_updated_data(original)
            await hass.async_block_till_done()
            returned = hass.states.get(zone.entity_id)
            assert returned is not None
            assert returned.state == "on"
            assert returned.attributes["role"] == "primary"
            assert returned.attributes["zone_id"] == PRIMARY_ZONE_ID
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_hub_entities_include_product_and_instance_namespace(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    master = first_state(hass, "light", lambda state: "active_effect_id" in state.attributes)

    assert master.entity_id == "light.hypercolor_hyperia"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_daemon_devices_link_to_the_hub_without_deprecated_calls(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    registry = dr.async_get(hass)
    hub = registry.async_get_device_by_identifier((DOMAIN, "srv_e2e"), entry.entry_id)
    child = registry.async_get_device_by_identifier(
        (DOMAIN, "srv_e2e:device:wled-studio"), entry.entry_id
    )

    assert hub is not None
    assert child is not None
    assert child.via_device_id == hub.id
    assert entry.runtime_data.hub_device_id == hub.id
    assert "Detected that custom integration" not in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_stores_the_new_key_without_deprecated_calls(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "rotated-key"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "rotated-key"
    assert entry.state is ConfigEntryState.LOADED
    assert "Detected that custom integration" not in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_change_reloads_the_entry_without_deprecated_calls(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    original_runtime = entry.runtime_data

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**entry.options, CONF_RECONCILE_INTERVAL_S: 120}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_RECONCILE_INTERVAL_S] == 120
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not original_runtime
    assert "Detected that custom integration" not in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)


# Home Assistant's own http component still stores string app keys.
@pytest.mark.filterwarnings("ignore::aiohttp.web_exceptions.NotAppKeyWarning")
async def test_daemon_devices_detach_through_the_ui_without_deprecated_calls(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert await async_setup_component(hass, "config", {})
    entry = await setup_entry(hass, port=fake_daemon.port)
    registry = dr.async_get(hass)
    hub = registry.async_get_device_by_identifier((DOMAIN, "srv_e2e"), entry.entry_id)
    child = registry.async_get_device_by_identifier(
        (DOMAIN, "srv_e2e:device:wled-studio"), entry.entry_id
    )
    assert hub is not None
    assert child is not None
    client = await hass_ws_client(hass)

    responses = {}
    for name, device_id in (("hub", hub.id), ("child", child.id)):
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove",
                "device_id": device_id,
            }
        )
        responses[name] = await client.receive_json()

    assert responses["hub"]["success"] is False
    assert responses["child"]["success"] is True
    assert registry.async_get(hub.id) is not None
    assert registry.async_get(child.id) is None
    assert "Detected that custom integration" not in caplog.text
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_card_facing_entities_publish_stable_translation_keys(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    entries = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    translation_keys = {item.unique_id: item.translation_key for item in entries}

    expected = {
        "srv_e2e:connected": "connected",
        "srv_e2e:active_effect": "active_effect",
        "srv_e2e:scene": "scene",
        "srv_e2e:layout": "layout",
        "srv_e2e:preset": "preset",
        "srv_e2e:next_effect": "next_effect",
        "srv_e2e:stop_effect": "stop_effect",
        "srv_e2e:control:brightness": "brightness",
        "srv_e2e:device:wled-studio:identify": "identify",
        "srv_e2e:device:wled-studio:enabled": "enabled",
    }
    assert expected.items() <= translation_keys.items()
    assert "srv_e2e:profile" not in translation_keys
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_stale_zone_entities_are_pruned_at_setup(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port, setup=False)
    entity_registry = er.async_get(hass)
    stale = entity_registry.async_get_or_create(
        "light",
        DOMAIN,
        "srv_e2e:zone:zone-deleted-long-ago",
        config_entry=entry,
    )

    await activate_entry(hass, entry)

    assert entity_registry.async_get(stale.entity_id) is None
    assert (
        entity_registry.async_get_entity_id("light", DOMAIN, f"srv_e2e:zone:{PRIMARY_ZONE_ID}")
        is not None
    )
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_retired_profile_select_is_removed_on_upgrade(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port, setup=False)
    entity_registry = er.async_get(hass)
    legacy = entity_registry.async_get_or_create(
        "select",
        DOMAIN,
        "srv_e2e:profile",
        config_entry=entry,
    )

    await activate_entry(hass, entry)

    assert entity_registry.async_get(legacy.entity_id) is None
    assert entity_registry.async_get_entity_id("select", DOMAIN, "srv_e2e:scene") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_master_pause_resume_preserves_exact_effect_state(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    master = first_state(hass, "light", lambda state: "active_effect_id" in state.attributes)
    assert master.state == "on"
    assert master.attributes["effect"] == "Rainbow"
    assert master.attributes["brightness"] == 204

    await hass.services.async_call(
        "light", "turn_off", {"entity_id": master.entity_id}, blocking=True
    )
    stopped = hass.states.get(master.entity_id)
    assert stopped is not None
    assert stopped.state == "off"

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": master.entity_id}, blocking=True
    )
    assert fake_daemon.pause_requests == 1
    assert fake_daemon.resume_requests == 1
    assert fake_daemon.active_effect_id == "rainbow"
    assert fake_daemon.active_preset_id == "preset-rainbow"
    assert fake_daemon.scalar_control_values == {"speed": 60.0, "brightness": 80.0}
    assert fake_daemon.applied_effects == []
    resumed = hass.states.get(master.entity_id)
    assert resumed is not None
    assert resumed.state == "on"
    assert resumed.attributes["effect"] == "Rainbow"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_master_brightness_writes_the_output_fraction(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    master = first_state(hass, "light", lambda state: "active_effect_id" in state.attributes)

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": master.entity_id, "brightness": 128},
        blocking=True,
    )

    assert fake_daemon.brightness == 0.502
    updated = hass.states.get(master.entity_id)
    assert updated is not None
    assert updated.attributes["brightness"] == 128
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_master_turn_off_and_stop_button_are_idempotent(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    master = first_state(hass, "light", lambda state: "active_effect_id" in state.attributes)
    stop_button = first_state(
        hass,
        "button",
        lambda state: state.entity_id.endswith("_stop_effect"),
    )

    for _ in range(2):
        await hass.services.async_call(
            "light",
            "turn_off",
            {"entity_id": master.entity_id},
            blocking=True,
        )
    for _ in range(2):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": stop_button.entity_id},
            blocking=True,
        )

    assert fake_daemon.pause_requests == 2
    assert fake_daemon.clear_requests == 2
    stopped = hass.states.get(master.entity_id)
    assert stopped is not None
    assert stopped.attributes["active_effect_id"] is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_selecting_effect_while_paused_uses_effect_apply_wake(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    master = first_state(hass, "light", lambda state: "active_effect_id" in state.attributes)

    await hass.services.async_call(
        "light", "turn_off", {"entity_id": master.entity_id}, blocking=True
    )
    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": master.entity_id, "effect": "Solid Color"},
        blocking=True,
    )

    assert fake_daemon.active_effect_id == "solid_color"
    assert fake_daemon.paused is False
    assert fake_daemon.resume_requests == 0
    assert await hass.config_entries.async_unload(entry.entry_id)
