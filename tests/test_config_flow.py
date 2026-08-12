from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from homeassistant.config_entries import ConfigEntryState

from custom_components.hypercolor import async_migrate_entry
from custom_components.hypercolor.config_flow import _device_options


def test_device_options_use_live_devices_and_preserve_selected_missing_ids() -> None:
    entry: Any = SimpleNamespace(
        state=ConfigEntryState.LOADED,
        runtime_data=SimpleNamespace(
            coordinators={
                "devices": SimpleNamespace(data=[{"id": "wled-office", "name": "Office WLED"}])
            }
        ),
    )

    options = _device_options(entry, ["corsair-offline"])

    assert options == [
        {"value": "corsair-offline", "label": "corsair-offline"},
        {"value": "wled-office", "label": "Office WLED"},
    ]


async def test_migration_disables_legacy_default_polling_and_dead_channel() -> None:
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
