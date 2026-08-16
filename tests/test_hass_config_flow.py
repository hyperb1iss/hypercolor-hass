from __future__ import annotations

from ipaddress import IPv4Address
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hypercolor import async_migrate_entry, config_flow
from custom_components.hypercolor.api import CannotConnectError, InvalidAuthError, ServerInfo
from custom_components.hypercolor.const import CONF_API_KEY, DOMAIN, OPTIONS_DEFAULTS


def test_device_options_use_live_devices_and_preserve_selected_missing_ids() -> None:
    entry: Any = SimpleNamespace(
        state=ConfigEntryState.LOADED,
        runtime_data=SimpleNamespace(
            snapshot=SimpleNamespace(
                devices=(SimpleNamespace(id="wled-office", name="Office WLED"),)
            )
        ),
    )

    options = config_flow._device_options(entry, ["corsair-offline"])

    assert options == [
        {"value": "corsair-offline", "label": "corsair-offline"},
        {"value": "wled-office", "label": "Office WLED"},
    ]


async def test_migration_disables_legacy_polling_and_dead_channel() -> None:
    updates: dict[str, Any] = {}
    hass: Any = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_update_entry=lambda _entry, **values: updates.update(values)
        )
    )
    entry: Any = SimpleNamespace(
        version=1,
        minor_version=1,
        options={
            "reconcile_interval_s": 60,
            "channels.device_metrics": True,
        },
    )

    assert await async_migrate_entry(hass, entry)
    assert updates["minor_version"] == 2
    assert updates["options"]["reconcile_interval_s"] == 0
    assert "channels.device_metrics" not in updates["options"]


async def test_user_flow_creates_entry(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch,
) -> None:
    validate = AsyncMock(return_value=_server())
    monkeypatch.setattr(config_flow, "_validate", validate)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "hyperia.local", CONF_PORT: 9420, CONF_API_KEY: " control-key "},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Hyperia"
    assert result["data"] == {
        CONF_HOST: "hyperia.local",
        CONF_PORT: 9420,
        CONF_API_KEY: "control-key",
    }
    assert result["options"] == OPTIONS_DEFAULTS
    validate.assert_awaited_once()


async def test_user_flow_reports_connection_and_auth_failures(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch,
) -> None:
    for error, expected in (
        (CannotConnectError(), "cannot_connect"),
        (InvalidAuthError(), "invalid_auth"),
    ):
        monkeypatch.setattr(config_flow, "_validate", AsyncMock(side_effect=error))
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "hyperia.local", CONF_PORT: 9420},
        )

        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected}


async def test_zeroconf_flow_decodes_identity_and_confirms(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    monkeypatch,
) -> None:
    monkeypatch.setattr(config_flow, "_validate", AsyncMock(return_value=_server()))
    monkeypatch.setattr(
        "custom_components.hypercolor.async_setup_entry",
        AsyncMock(return_value=True),
    )
    address = IPv4Address("192.168.1.50")
    discovery = ZeroconfServiceInfo(
        ip_address=address,
        ip_addresses=[address],
        port=9420,
        hostname="hyperia.local.",
        type="_hypercolor._tcp.local.",
        name="Hyperia._hypercolor._tcp.local.",
        properties={"id": b"srv-1", "name": b"Hyperia", "version": b"0.3.1"},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=discovery,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zeroconf_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "control-key"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.50"


async def test_zeroconf_flow_aborts_duplicate_instance(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    existing = MockConfigEntry(domain=DOMAIN, unique_id="srv-1")
    existing.add_to_hass(hass)
    address = IPv4Address("192.168.1.50")

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=ZeroconfServiceInfo(
            ip_address=address,
            ip_addresses=[address],
            port=9420,
            hostname="hyperia.local.",
            type="_hypercolor._tcp.local.",
            name="Hyperia._hypercolor._tcp.local.",
            properties={"id": "srv-1", "name": "Hyperia"},
        ),
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert existing.data[CONF_HOST] == "192.168.1.50"


async def test_options_flow_replaces_complete_option_set(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> None:
    entry = MockConfigEntry(domain=DOMAIN, options={**OPTIONS_DEFAULTS})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    options = {
        **OPTIONS_DEFAULTS,
        "reconcile_interval_s": 120,
        "channels.audio": True,
        "per_device_entities": [],
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], options)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == options


def _server() -> ServerInfo:
    return ServerInfo(
        instance_id="srv-1",
        instance_name="Hyperia",
        version="0.3.1",
        auth_required=True,
        device_count=3,
    )
