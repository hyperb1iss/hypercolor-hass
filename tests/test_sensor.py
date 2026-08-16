from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from custom_components.hypercolor import sensor


async def test_metrics_entities_follow_channel_option(monkeypatch) -> None:
    monkeypatch.setattr(sensor, "HypercolorActiveEffectSensor", lambda entry: "active")
    monkeypatch.setattr(sensor, "HypercolorFpsSensor", lambda entry: "fps")
    monkeypatch.setattr(sensor, "HypercolorRenderTimeSensor", lambda entry: "render_time")
    monkeypatch.setattr(sensor, "HypercolorAudioEnergySensor", lambda entry: "audio")
    entities: list[str] = []

    await sensor.async_setup_entry(
        cast(Any, None),
        cast(Any, SimpleNamespace(options={})),
        cast(Any, entities.extend),
    )
    assert entities == ["active"]

    entities.clear()
    await sensor.async_setup_entry(
        cast(Any, None),
        cast(Any, SimpleNamespace(options={"channels.metrics": True})),
        cast(Any, entities.extend),
    )
    assert entities == ["active", "fps", "render_time"]


def test_nested_metrics_match_websocket_contract() -> None:
    metrics = {
        "fps": {"actual": 59.8},
        "frame_time": {"avg_ms": 4.2},
    }

    assert sensor._nested_number(metrics, "fps", "actual") == 59.8
    assert sensor._nested_number(metrics, "frame_time", "avg_ms") == 4.2
    assert sensor._nested_number(metrics, "fps", "missing") is None
    assert sensor._nested_number({"fps": "unknown"}, "fps", "actual") is None
