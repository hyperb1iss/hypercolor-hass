from __future__ import annotations

from homeassistant.components.scene import DOMAIN as SCENE_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.hypercolor.const import DOMAIN
from tests.support import hypercolor_payloads as payloads
from tests.support.hass import activate_entry, setup_entry
from tests.support.hypercolor_daemon import FakeHypercolorDaemon

pytest_plugins = ("tests.support.fixtures",)

EVENING_UNIQUE_ID = "srv_e2e:scene:scene-evening"
PARTY_UNIQUE_ID = "srv_e2e:scene:scene-party"
RAINBOW_UNIQUE_ID = "srv_e2e:effect:rainbow"
SOLID_COLOR_UNIQUE_ID = "srv_e2e:effect:solid_color"


async def test_scene_platform_publishes_every_scene_and_effect(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)

    assert _entity_id(hass, EVENING_UNIQUE_ID) == "scene.hypercolor_hyperia_evening"
    assert _entity_id(hass, RAINBOW_UNIQUE_ID) == "scene.hypercolor_hyperia_effect_rainbow"
    assert _entity_id(hass, SOLID_COLOR_UNIQUE_ID) == "scene.hypercolor_hyperia_effect_solid_color"

    evening = hass.states.get("scene.hypercolor_hyperia_evening")
    assert evening is not None
    assert evening.attributes["friendly_name"] == "Hypercolor Hyperia Evening"
    assert evening.attributes["scene_id"] == "scene-evening"

    rainbow = hass.states.get("scene.hypercolor_hyperia_effect_rainbow")
    assert rainbow is not None
    assert rainbow.attributes["friendly_name"] == "Hypercolor Hyperia Effect: Rainbow"
    assert rainbow.attributes["effect_id"] == "rainbow"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_activating_a_scene_entity_calls_the_daemon_scene_route(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)

    await hass.services.async_call(
        SCENE_DOMAIN,
        "turn_on",
        {"entity_id": _entity_id(hass, EVENING_UNIQUE_ID)},
        blocking=True,
    )

    assert fake_daemon.activated_scenes == ["scene-evening"]
    assert fake_daemon.applied_effects == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_activating_an_effect_scene_applies_that_effect(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)

    await hass.services.async_call(
        SCENE_DOMAIN,
        "turn_on",
        {"entity_id": _entity_id(hass, SOLID_COLOR_UNIQUE_ID)},
        blocking=True,
    )

    assert fake_daemon.applied_effects == [{"effect_id": "solid_color", "controls": {}}]
    assert fake_daemon.active_effect_id == "solid_color"
    assert fake_daemon.activated_scenes == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_renaming_a_scene_upstream_keeps_the_entity_identity(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    entity_id = _entity_id(hass, EVENING_UNIQUE_ID)

    fake_daemon.scenes[0]["name"] = "Late Night"
    await _refresh(hass)

    assert _entity_id(hass, EVENING_UNIQUE_ID) == entity_id
    renamed = hass.states.get(entity_id)
    assert renamed is not None
    assert renamed.attributes["friendly_name"] == "Hypercolor Hyperia Late Night"

    await hass.services.async_call(
        SCENE_DOMAIN,
        "turn_on",
        {"entity_id": entity_id},
        blocking=True,
    )
    assert fake_daemon.activated_scenes == ["scene-evening"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_deleted_scene_takes_its_entity_with_it(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    fake_daemon.scenes.append(payloads.scene_summary(scene_id="scene-party", name="Party"))
    entry = await setup_entry(hass, port=fake_daemon.port)
    entity_id = _entity_id(hass, EVENING_UNIQUE_ID)
    survivor_id = _entity_id(hass, PARTY_UNIQUE_ID)

    fake_daemon.scenes[:] = [
        scene for scene in fake_daemon.scenes if scene["id"] != "scene-evening"
    ]
    await _refresh(hass)

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get_entity_id(SCENE_DOMAIN, DOMAIN, EVENING_UNIQUE_ID) is None
    assert hass.states.get(entity_id) is None
    assert _entity_id(hass, PARTY_UNIQUE_ID) == survivor_id
    assert hass.states.get(survivor_id) is not None
    assert _entity_id(hass, RAINBOW_UNIQUE_ID) == "scene.hypercolor_hyperia_effect_rainbow"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_scene_added_upstream_appears_without_a_reload(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    entity_registry = er.async_get(hass)
    assert entity_registry.async_get_entity_id(SCENE_DOMAIN, DOMAIN, PARTY_UNIQUE_ID) is None

    fake_daemon.scenes.append(payloads.scene_summary(scene_id="scene-party", name="Party"))
    await _refresh(hass)

    assert _entity_id(hass, PARTY_UNIQUE_ID) == "scene.hypercolor_hyperia_party"
    await hass.services.async_call(
        SCENE_DOMAIN,
        "turn_on",
        {"entity_id": _entity_id(hass, PARTY_UNIQUE_ID)},
        blocking=True,
    )
    assert fake_daemon.activated_scenes == ["scene-party"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_scenes_deleted_while_home_assistant_was_down_are_pruned_at_setup(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port, setup=False)
    entity_registry = er.async_get(hass)
    stale = entity_registry.async_get_or_create(
        SCENE_DOMAIN,
        DOMAIN,
        "srv_e2e:scene:scene-deleted-last-week",
        config_entry=entry,
    )

    await activate_entry(hass, entry)

    assert entity_registry.async_get(stale.entity_id) is None
    assert _entity_id(hass, EVENING_UNIQUE_ID) == "scene.hypercolor_hyperia_evening"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_removed_effect_loses_its_entity(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    entry = await setup_entry(hass, port=fake_daemon.port)
    rainbow_id = _entity_id(hass, RAINBOW_UNIQUE_ID)

    fake_daemon.effects[:] = [
        effect for effect in fake_daemon.effects if effect["id"] != "rainbow"
    ]
    await _refresh(hass)

    entity_registry = er.async_get(hass)
    assert entity_registry.async_get_entity_id(SCENE_DOMAIN, DOMAIN, RAINBOW_UNIQUE_ID) is None
    assert hass.states.get(rainbow_id) is None
    assert _entity_id(hass, SOLID_COLOR_UNIQUE_ID) == "scene.hypercolor_hyperia_effect_solid_color"
    assert _entity_id(hass, EVENING_UNIQUE_ID) == "scene.hypercolor_hyperia_evening"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_an_empty_catalog_waits_instead_of_pruning_everything(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    """A daemon serving nothing is mid-restart, not a user deleting everything."""
    entry = await setup_entry(hass, port=fake_daemon.port)
    evening_id = _entity_id(hass, EVENING_UNIQUE_ID)
    rainbow_id = _entity_id(hass, RAINBOW_UNIQUE_ID)

    fake_daemon.scenes.clear()
    fake_daemon.effects.clear()
    await _refresh(hass)

    assert _entity_id(hass, EVENING_UNIQUE_ID) == evening_id
    assert _entity_id(hass, RAINBOW_UNIQUE_ID) == rainbow_id
    evening = hass.states.get(evening_id)
    assert evening is not None
    assert evening.state == "unavailable"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_the_prune_leaves_rows_it_does_not_own_alone(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: FakeHypercolorDaemon,
) -> None:
    """A scene row under this entry but outside our prefixes is not ours to delete."""
    entry = await setup_entry(hass, port=fake_daemon.port, setup=False)
    entity_registry = er.async_get(hass)
    foreign = entity_registry.async_get_or_create(
        SCENE_DOMAIN,
        DOMAIN,
        "srv_e2e:something-else",
        config_entry=entry,
    )

    await activate_entry(hass, entry)
    fake_daemon.scenes.clear()
    await _refresh(hass)

    assert entity_registry.async_get(foreign.entity_id) is not None
    assert entity_registry.async_get_entity_id(SCENE_DOMAIN, DOMAIN, EVENING_UNIQUE_ID) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


def _entity_id(hass: HomeAssistant, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(SCENE_DOMAIN, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def _refresh(hass: HomeAssistant) -> None:
    """Pump one coordinator update, the way a daemon push event would."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
