from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any, Protocol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN
from .runtime_data import HypercolorRuntimeData


class _DeviceEntityFactory(Protocol):
    def __call__(self, entry: ConfigEntry[HypercolorRuntimeData], device: Any) -> Any: ...


class MultiCoordinatorEntity(CoordinatorEntity):
    def __init__(
        self,
        coordinator: DataUpdateCoordinator[Any],
        *secondary_coordinators: DataUpdateCoordinator[Any],
    ) -> None:
        super().__init__(coordinator)
        self._secondary_coordinators = secondary_coordinators

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for coordinator in self._secondary_coordinators:
            self.async_on_remove(coordinator.async_add_listener(self._handle_secondary_update))

    @callback
    def _handle_secondary_update(self) -> None:
        self.async_write_ha_state()


def add_configured_device_entities(
    entry: ConfigEntry[HypercolorRuntimeData],
    async_add_entities: AddEntitiesCallback,
    factory: _DeviceEntityFactory,
) -> None:
    coordinator = entry.runtime_data.coordinators["devices"]
    known_ids: set[str] = set()

    @callback
    def sync_entities() -> None:
        configured_ids = set(entry.options.get("per_device_entities", []))
        fresh = [
            device
            for device in coordinator.data or []
            if (device_id := str(read_field(device, "id"))) in configured_ids
            and device_id not in known_ids
        ]
        if not fresh:
            return
        known_ids.update(str(read_field(device, "id")) for device in fresh)
        async_add_entities([factory(entry, device) for device in fresh])

    sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(sync_entities))


def hub_device_info(runtime: HypercolorRuntimeData, entry_data: Mapping[str, Any]) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, runtime.server.instance_id)},
        name=runtime.server.instance_name,
        manufacturer="Hypercolor",
        model="Daemon",
        sw_version=runtime.server.version,
        configuration_url=f"http://{entry_data['host']}:{entry_data['port']}",
    )


def child_device_info(runtime: HypercolorRuntimeData, device: Any) -> DeviceInfo:
    device_id = str(read_field(device, "id"))
    name = str(read_field(device, "name", device_id))
    return DeviceInfo(
        identifiers={(DOMAIN, child_device_identifier(runtime, device_id))},
        name=name,
        manufacturer=str(read_field(device, "vendor", "Hypercolor")),
        model=str(read_field(device, "backend", read_field(device, "family", "LED device"))),
        sw_version=read_field(device, "firmware_version"),
        via_device=(DOMAIN, runtime.server.instance_id),
    )


def child_device_identifier(runtime: HypercolorRuntimeData, device_id: str) -> str:
    return f"{runtime.server.instance_id}:device:{device_id}"


def catalog_items(catalog: Any, key: str) -> list[Any]:
    if isinstance(catalog, Mapping):
        value = catalog.get(key, [])
        return list(value) if isinstance(value, list) else []
    if key == "effects" and isinstance(catalog, list):
        return catalog
    return []


def option_map(items: list[Any]) -> dict[str, str]:
    name_counts = Counter(item_name(item) for item in items)
    return {item_option(item, name_counts): item_id(item) for item in items}


def item_option(item: Any, name_counts: Mapping[str, int]) -> str:
    name = item_name(item)
    return name if name_counts[name] == 1 else f"{name} ({item_id(item)})"


def item_id(item: Any) -> str:
    return str(read_field(item, "id", read_field(item, "name")))


def item_name(item: Any) -> str:
    return str(read_field(item, "name", read_field(item, "id")))


def read_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)


def control_scalar(value: Any) -> Any:
    """Unwrap a daemon control value to its scalar.

    The daemon serializes control values externally tagged, e.g.
    ``{"float": 12.0}`` or ``{"enum": "Palette Blend"}``; older payloads
    and the control patch path use bare scalars. Colors, gradients, and
    rects stay as-is.
    """
    if isinstance(value, dict) and len(value) == 1:
        inner = next(iter(value.values()))
        if isinstance(inner, (int, float, str, bool)):
            return inner
    return value
