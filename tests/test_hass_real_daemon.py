from __future__ import annotations

import os

import pytest
from homeassistant.core import HomeAssistant

from tests.support.hass import first_state, setup_entry


@pytest.mark.e2e
@pytest.mark.skipif(
    os.environ.get("HYPERCOLOR_HASS_REAL_E2E") != "1",
    reason="set HYPERCOLOR_HASS_REAL_E2E=1 to use a running local daemon",
)
async def test_real_daemon_config_entry_boots(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    socket_enabled: None,
) -> None:
    entry = await setup_entry(
        hass,
        host=os.environ.get("HYPERCOLOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("HYPERCOLOR_PORT", "9420")),
    )

    master = first_state(hass, "light", lambda state: bool(state.attributes.get("effect_list")))
    assert master.state in {"on", "off"}
    assert master.attributes["effect_list"]
    assert await hass.config_entries.async_unload(entry.entry_id)
