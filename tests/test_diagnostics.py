from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hypercolor.api import ServerInfo
from custom_components.hypercolor.const import CONF_API_KEY, DOMAIN
from custom_components.hypercolor.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.hypercolor.runtime_data import ConnectionState


async def test_config_entry_diagnostics_redact_credentials(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "hyperia.local", CONF_API_KEY: "control-key"},
        options={"reconcile_interval_s": 60},
    )
    entry.runtime_data = SimpleNamespace(
        server=ServerInfo(
            instance_id="srv-1",
            instance_name="Hyperia",
            version="0.3.2",
            auth_required=True,
            device_count=3,
        ),
        connection_state=ConnectionState(),
        coordinator=SimpleNamespace(last_update_success=True),
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, cast(Any, entry))

    assert diagnostics["config"][CONF_API_KEY] == "**REDACTED**"
    assert diagnostics["config"]["host"] == "**REDACTED**"
    assert diagnostics["server"]["instance_id"] == "srv-1"
    assert diagnostics["snapshot_coordinator"] is True


async def test_device_diagnostics_serialize_registry_identity(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, entry_id="entry-1")
    device = cast(
        DeviceEntry,
        SimpleNamespace(
            id="device-1",
            identifiers={(DOMAIN, "wled-studio")},
            name="Studio WLED",
        ),
    )

    diagnostics = await async_get_device_diagnostics(hass, cast(Any, entry), device)

    assert diagnostics == {
        "config_entry_id": "entry-1",
        "device": {
            "id": "device-1",
            "identifiers": [[DOMAIN, "wled-studio"]],
            "name": "Studio WLED",
        },
    }
