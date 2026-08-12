from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.httpx_client import get_async_client

from hypercolor import HypercolorClient

from .api import (
    CannotConnectError,
    InvalidAuthError,
    UnsupportedDaemonError,
    async_validate_daemon,
)
from .const import (
    CONF_API_KEY,
    CONF_RECONCILE_INTERVAL_S,
    DOMAIN,
    OPTIONS_DEFAULTS,
    PLATFORMS,
)
from .coordinator import (
    HypercolorCoordinator,
    load_audio,
    load_catalog,
    load_metrics,
    load_state,
    reconcile_loop,
    websocket_loop,
)
from .entity import child_device_identifier, read_field
from .runtime_data import HypercolorRuntimeData
from .services import async_setup_services

type HypercolorConfigEntry = ConfigEntry[HypercolorRuntimeData]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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
    except UnsupportedDaemonError as exc:
        raise ConfigEntryError(
            "The Hypercolor daemon does not support persistent output pause"
        ) from exc

    client = HypercolorClient(
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
        loader=lambda: load_state(client),
        connection_state=runtime_data.connection_state,
    )
    catalog = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="catalog",
        loader=lambda: load_catalog(client),
        connection_state=runtime_data.connection_state,
    )
    devices = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="devices",
        loader=client.get_devices,
        connection_state=runtime_data.connection_state,
    )
    metrics = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="metrics",
        loader=lambda: load_metrics(client),
        connection_state=runtime_data.connection_state,
    )
    audio = HypercolorCoordinator(
        hass,
        config_entry=entry,
        name="audio",
        loader=lambda: load_audio(client),
        connection_state=runtime_data.connection_state,
    )
    runtime_data.coordinators.update(
        {
            "state": state,
            "catalog": catalog,
            "devices": devices,
            "metrics": metrics,
            "audio": audio,
        }
    )
    await state.async_config_entry_first_refresh()
    await catalog.async_config_entry_first_refresh()
    await devices.async_config_entry_first_refresh()
    if entry.options.get("channels.metrics", OPTIONS_DEFAULTS["channels.metrics"]):
        await metrics.async_config_entry_first_refresh()
    if entry.options.get("channels.audio", OPTIONS_DEFAULTS["channels.audio"]):
        await audio.async_config_entry_first_refresh()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _register_child_devices(hass, entry, devices.data)
    _cleanup_opted_out_entities(hass, entry)
    _cleanup_stale_zone_entities(hass, entry, state.data)

    reconcile_interval_s = int(
        entry.options.get(CONF_RECONCILE_INTERVAL_S, OPTIONS_DEFAULTS[CONF_RECONCILE_INTERVAL_S])
    )
    if reconcile_interval_s > 0:
        runtime_data.reconcile_task = entry.async_create_background_task(
            hass,
            reconcile_loop([state, catalog, devices], reconcile_interval_s),
            name="hypercolor.reconcile",
        )
    runtime_data.ws_task = entry.async_create_background_task(
        hass,
        websocket_loop(runtime_data, {**OPTIONS_DEFAULTS, **entry.options}),
        name="hypercolor.ws",
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HypercolorConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime = entry.runtime_data

    tasks = [
        task
        for task in (runtime.ws_task, runtime.reconcile_task, runtime.unavailable_task)
        if task is not None
    ]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await runtime.client.aclose()

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: HypercolorConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version == 1 and entry.minor_version < 2:
        options = {**OPTIONS_DEFAULTS, **entry.options}
        if options[CONF_RECONCILE_INTERVAL_S] == 60:
            options[CONF_RECONCILE_INTERVAL_S] = 0
        options.pop("channels.device_metrics", None)
        hass.config_entries.async_update_entry(
            entry,
            minor_version=2,
            options=options,
        )
    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: HypercolorConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    runtime = entry.runtime_data
    hub_identifier = (DOMAIN, runtime.server.instance_id)
    if hub_identifier in device_entry.identifiers:
        return False

    device_registry = dr.async_get(hass)
    device_registry.async_update_device(
        device_entry.id,
        remove_config_entry_id=entry.entry_id,
    )
    return True


def _register_child_devices(
    hass: HomeAssistant,
    entry: HypercolorConfigEntry,
    devices: list[Any],
) -> None:
    device_registry = dr.async_get(hass)
    runtime = entry.runtime_data
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, runtime.server.instance_id)},
        name=runtime.server.instance_name,
        manufacturer="Hypercolor",
        model="Daemon",
        sw_version=runtime.server.version,
        configuration_url=(f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"),
    )
    for device in devices or []:
        device_id = str(read_field(device, "id"))
        if not device_id:
            continue
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, child_device_identifier(runtime, device_id))},
            name=str(read_field(device, "name", device_id)),
            manufacturer=str(read_field(device, "vendor", "Hypercolor")),
            model=str(read_field(device, "backend", read_field(device, "family", "LED device"))),
            sw_version=read_field(device, "firmware_version"),
            via_device=(DOMAIN, runtime.server.instance_id),
        )


def _cleanup_opted_out_entities(
    hass: HomeAssistant,
    entry: HypercolorConfigEntry,
) -> None:
    entity_registry = er.async_get(hass)
    runtime = entry.runtime_data
    opted_in = set(entry.options.get("per_device_entities", []))
    prefix = f"{runtime.server.instance_id}:device:"
    suffixes = (":light", ":identify", ":enabled")
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if not registry_entry.unique_id.startswith(prefix):
            continue
        suffix = next(
            (candidate for candidate in suffixes if registry_entry.unique_id.endswith(candidate)),
            None,
        )
        if suffix is None:
            continue
        device_id = registry_entry.unique_id[len(prefix) : -len(suffix)]
        if device_id in opted_in:
            continue
        entity_registry.async_remove(registry_entry.entity_id)


def _cleanup_stale_zone_entities(
    hass: HomeAssistant,
    entry: HypercolorConfigEntry,
    state: Any,
) -> None:
    """Prune zone lights whose zones no longer exist.

    Zone ids are per-scene UUIDs, so zone churn would otherwise grow the
    registry without bound. Pruning happens at setup only — mid-session
    scene switches leave entities unavailable rather than yanking them
    out from under dashboards.
    """
    entity_registry = er.async_get(hass)
    runtime = entry.runtime_data
    current_zone_ids = {
        str(read_field(zone, "id")) for zone in read_field(state, "zones", []) or []
    }
    prefix = f"{runtime.server.instance_id}:zone:"
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if not registry_entry.unique_id.startswith(prefix):
            continue
        zone_id = registry_entry.unique_id.removeprefix(prefix)
        if zone_id not in current_zone_ids:
            entity_registry.async_remove(registry_entry.entity_id)
