from __future__ import annotations

from collections.abc import Callable

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hypercolor.const import (
    CONF_API_KEY,
    CONF_CHANNELS_AUDIO,
    CONF_CHANNELS_METRICS,
    CONF_LIVE_CONTROLS_ENABLED,
    CONF_PER_DEVICE_ENTITIES,
    CONF_RECONCILE_INTERVAL_S,
    DOMAIN,
    OPTIONS_DEFAULTS,
)


async def setup_entry(
    hass: HomeAssistant,
    *,
    host: str = "127.0.0.1",
    port: int,
    setup: bool = True,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hypercolor E2E",
        unique_id="srv_e2e",
        data={
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_API_KEY: None,
        },
        options={
            **OPTIONS_DEFAULTS,
            CONF_RECONCILE_INTERVAL_S: 3600,
            CONF_CHANNELS_AUDIO: False,
            CONF_CHANNELS_METRICS: False,
            CONF_LIVE_CONTROLS_ENABLED: True,
            CONF_PER_DEVICE_ENTITIES: ["wled-studio"],
        },
    )
    entry.add_to_hass(hass)
    if setup:
        await activate_entry(hass, entry)
    return entry


async def activate_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def first_state(
    hass: HomeAssistant,
    domain: str,
    predicate: Callable[[State], bool],
) -> State:
    for state in hass.states.async_all(domain):
        if predicate(state):
            return state
    msg = f"No {domain} entity matched predicate"
    raise AssertionError(msg)
