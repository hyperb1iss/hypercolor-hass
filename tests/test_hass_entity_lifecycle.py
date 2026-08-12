from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hypercolor.const import DOMAIN
from tests.support.hass import activate_entry, first_state, setup_entry
from tests.support.hypercolor_daemon import FakeHypercolorDaemon

pytest_plugins = ("tests.support.fixtures",)


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
        entity_registry.async_get_entity_id("light", DOMAIN, "srv_e2e:zone:zone-primary")
        is not None
    )
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
    assert fake_daemon.control_values == {"speed": 60.0, "brightness": 80.0}
    assert fake_daemon.applied_effects == []
    resumed = hass.states.get(master.entity_id)
    assert resumed is not None
    assert resumed.state == "on"
    assert resumed.attributes["effect"] == "Rainbow"
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
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": stop_button.entity_id},
        blocking=True,
    )
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": stop_button.entity_id},
        blocking=True,
    )

    assert fake_daemon.pause_requests == 2
    assert fake_daemon.stop_requests == 2
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
