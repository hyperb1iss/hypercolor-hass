from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from custom_components.hypercolor.entity import add_configured_device_entities


def test_configured_device_entities_follow_live_discovery() -> None:
    coordinator = _Coordinator([{"id": "wled-office"}])
    entry: Any = SimpleNamespace(
        options={"per_device_entities": ["wled-office", "corsair-lcd"]},
        runtime_data=SimpleNamespace(coordinators={"devices": coordinator}),
        async_on_unload=lambda remove: None,
    )
    added: list[str] = []

    def add_entities(entities: list[Any]) -> None:
        added.extend(str(entity) for entity in entities)

    add_configured_device_entities(
        entry,
        cast(Any, add_entities),
        cast(Any, lambda _entry, device: str(device["id"])),
    )
    coordinator.data.append({"id": "corsair-lcd"})
    coordinator.listener()
    coordinator.listener()

    assert added == ["wled-office", "corsair-lcd"]


class _Coordinator:
    def __init__(self, data: list[dict[str, str]]) -> None:
        self.data = data
        self.listener = lambda: None

    def async_add_listener(self, listener: Any) -> Any:
        self.listener = listener
        return lambda: None
