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
from hypercolor.models import DeviceSummary

from .api import (
    CannotConnectError,
    InvalidAuthError,
    UnsupportedDaemonError,
    async_validate_daemon,
    url_host,
)
from .const import (
    CONF_API_KEY,
    CONF_CHANNELS_AUDIO,
    CONF_RECONCILE_INTERVAL_S,
    DOMAIN,
    OPTIONS_DEFAULTS,
    PLATFORMS,
)
from .coordinator import (
    HypercolorCoordinator,
    load_snapshot,
    reconcile_loop,
    websocket_loop,
)
from .entity import child_device_info, hub_device_info
from .models import HypercolorState
from .runtime_data import ConnectionSource, ConnectionState, HypercolorRuntimeData
from .services import async_setup_services

type HypercolorConfigEntry = ConfigEntry[HypercolorRuntimeData]

RETIRED_UNIQUE_SUFFIXES = ("profile",)

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
            "The Hypercolor daemon does not expose the output resource"
        ) from exc

    client = HypercolorClient(
        host=url_host(entry.data[CONF_HOST]),
        port=entry.data[CONF_PORT],
        api_key=entry.data.get(CONF_API_KEY),
        httpx_client=httpx_client,
    )
    connection_state = ConnectionState()
    connection_state.set_connected(ConnectionSource.SNAPSHOT)
    coordinator = HypercolorCoordinator(
        hass,
        config_entry=entry,
        loader=lambda previous: load_snapshot(
            client,
            load_audio=bool(
                entry.options.get(
                    CONF_CHANNELS_AUDIO,
                    OPTIONS_DEFAULTS[CONF_CHANNELS_AUDIO],
                )
            ),
            previous=previous,
        ),
        connection_state=connection_state,
    )
    runtime_data = HypercolorRuntimeData(
        client=client,
        server=server,
        coordinator=coordinator,
        connection_state=connection_state,
    )
    entry.runtime_data = runtime_data
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    def sync_devices() -> None:
        _register_child_devices(hass, entry, runtime_data.snapshot.devices)

    sync_devices()
    entry.async_on_unload(runtime_data.coordinator.async_add_listener(sync_devices))
    _cleanup_opted_out_entities(hass, entry)
    _cleanup_retired_entities(hass, entry)
    _cleanup_stale_zone_entities(hass, entry, runtime_data.snapshot.state)

    reconcile_interval_s = int(
        entry.options.get(CONF_RECONCILE_INTERVAL_S, OPTIONS_DEFAULTS[CONF_RECONCILE_INTERVAL_S])
    )
    if reconcile_interval_s > 0:
        runtime_data.reconcile_task = entry.async_create_background_task(
            hass,
            reconcile_loop(coordinator, reconcile_interval_s),
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
        for task in (
            runtime.ws_task,
            runtime.reconcile_task,
            runtime.coordinator.unavailable_task,
            *runtime.refresh_tasks,
        )
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
    devices: tuple[DeviceSummary, ...],
) -> None:
    device_registry = dr.async_get(hass)
    runtime = entry.runtime_data
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **hub_device_info(runtime, entry.data),
    )
    for device in devices:
        if not device.id:
            continue
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **child_device_info(runtime, device),
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
        if device_id not in opted_in:
            entity_registry.async_remove(registry_entry.entity_id)


def _cleanup_retired_entities(
    hass: HomeAssistant,
    entry: HypercolorConfigEntry,
) -> None:
    """Drop registry rows for entities this integration no longer creates.

    Profiles folded into scenes upstream, so the profile select has no
    successor entity and would otherwise linger as a dead row after an
    upgrade.
    """
    entity_registry = er.async_get(hass)
    runtime = entry.runtime_data
    retired = {f"{runtime.server.instance_id}:{suffix}" for suffix in RETIRED_UNIQUE_SUFFIXES}
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if registry_entry.unique_id in retired:
            entity_registry.async_remove(registry_entry.entity_id)


def _cleanup_stale_zone_entities(
    hass: HomeAssistant,
    entry: HypercolorConfigEntry,
    state: HypercolorState,
) -> None:
    """Prune zone lights whose zones no longer exist.

    Zone ids are per-scene UUIDs, so zone churn would otherwise grow the
    registry without bound. Pruning happens at setup only; mid-session
    scene switches leave entities unavailable rather than yanking them
    out from under dashboards.
    """
    entity_registry = er.async_get(hass)
    runtime = entry.runtime_data
    current_zone_ids = {zone.id for zone in state.zones}
    prefix = f"{runtime.server.instance_id}:zone:"
    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if not registry_entry.unique_id.startswith(prefix):
            continue
        zone_id = registry_entry.unique_id.removeprefix(prefix)
        if zone_id not in current_zone_ids:
            entity_registry.async_remove(registry_entry.entity_id)
