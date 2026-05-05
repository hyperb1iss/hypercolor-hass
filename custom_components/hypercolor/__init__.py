from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.httpx_client import get_async_client

from .api import CannotConnectError, InvalidAuthError, async_validate_daemon
from .client import create_hypercolor_client
from .const import (
    CONF_API_KEY,
    CONF_RECONCILE_INTERVAL_S,
    OPTIONS_DEFAULTS,
    PLATFORMS,
)
from .coordinator import HypercolorCoordinator, reconcile_loop
from .runtime_data import HypercolorRuntimeData
from .services import async_setup_services

type HypercolorConfigEntry = ConfigEntry[HypercolorRuntimeData]


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HypercolorConfigEntry) -> bool:
    httpx_client = get_async_client(hass)
    try:
        server = await async_validate_daemon(
            httpx_client,
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            api_key=entry.data.get(CONF_API_KEY),
        )
    except CannotConnectError as exc:
        raise ConfigEntryNotReady from exc
    except InvalidAuthError as exc:
        raise ConfigEntryAuthFailed from exc

    client = create_hypercolor_client(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        api_key=entry.data.get(CONF_API_KEY),
        httpx_client=httpx_client,
    )
    runtime_data = HypercolorRuntimeData(
        client=client,
        server=server,
    )
    runtime_data.connection_state.set_connected()
    entry.runtime_data = runtime_data
    state = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="state",
        loader=client.get_status,
        connection_state=runtime_data.connection_state,
    )
    catalog = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="catalog",
        loader=client.get_effects,
        connection_state=runtime_data.connection_state,
    )
    devices = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="devices",
        loader=client.get_devices,
        connection_state=runtime_data.connection_state,
    )
    runtime_data.coordinators.update(
        {
            "state": state,
            "catalog": catalog,
            "devices": devices,
        }
    )
    await state.async_config_entry_first_refresh()
    await catalog.async_config_entry_first_refresh()
    await devices.async_config_entry_first_refresh()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    reconcile_interval_s = int(
        entry.options.get(CONF_RECONCILE_INTERVAL_S, OPTIONS_DEFAULTS[CONF_RECONCILE_INTERVAL_S])
    )
    runtime_data.reconcile_task = entry.async_create_background_task(
        hass,
        reconcile_loop([state, catalog, devices], reconcile_interval_s),
        name="hypercolor.reconcile",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HypercolorConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime = entry.runtime_data

    tasks = [task for task in (runtime.ws_task, runtime.reconcile_task) if task is not None]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    if hasattr(runtime.client, "aclose"):
        await runtime.client.aclose()

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: HypercolorConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version == 1 and entry.minor_version < 1:
        hass.config_entries.async_update_entry(
            entry,
            minor_version=1,
            options={**OPTIONS_DEFAULTS, **entry.options},
        )
    return True
