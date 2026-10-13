from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components import hypercolor
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hypercolor.api import HostNotAllowedError
from custom_components.hypercolor.const import CONF_API_KEY, DOMAIN, OPTIONS_DEFAULTS


async def test_a_refused_host_name_retries_setup(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="srv-1",
        data={CONF_HOST: "hyperia.lan", CONF_PORT: 9420, CONF_API_KEY: None},
        options={**OPTIONS_DEFAULTS},
    )
    entry.add_to_hass(hass)
    monkeypatch.setattr(
        hypercolor, "async_validate_daemon", AsyncMock(side_effect=HostNotAllowedError())
    )

    assert not await hass.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY
