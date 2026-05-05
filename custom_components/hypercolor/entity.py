from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

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


def read_field(value: Any, field: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(field, default)
    return getattr(value, field, default)
