from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import slugify

from .const import DOMAIN
from .runtime_data import HypercolorRuntimeData


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


def device_slug(device_id: str) -> str:
    return slugify(device_id).replace("__", "_")


def catalog_items(catalog: Any, key: str) -> list[Any]:
    if isinstance(catalog, Mapping):
        value = catalog.get(key, [])
        return list(value) if isinstance(value, list) else []
    if key == "effects" and isinstance(catalog, list):
        return catalog
    return []


def option_map(items: list[Any]) -> dict[str, str]:
    return {item_name(item): item_id(item) for item in items}


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
