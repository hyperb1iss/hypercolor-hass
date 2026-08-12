from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from custom_components.hypercolor.sensor import HypercolorFpsSensor, HypercolorRenderTimeSensor


def test_metrics_sensors_read_nested_daemon_payload() -> None:
    coordinator = SimpleNamespace(
        data={
            "fps": {"actual": 58.75, "target": 60},
            "frame_time": {"avg_ms": 4.25, "p95_ms": 7.5},
        },
        last_update_success=True,
    )
    entry: Any = SimpleNamespace(
        data={"host": "hyperia", "port": 9420},
        runtime_data=SimpleNamespace(
            server=SimpleNamespace(
                instance_id="srv-1",
                instance_name="Hyperia",
                version="0.3.2",
            ),
            coordinators={"metrics": coordinator},
        ),
    )

    assert HypercolorFpsSensor(entry).native_value == 58.75
    assert HypercolorRenderTimeSensor(entry).native_value == 4.25
