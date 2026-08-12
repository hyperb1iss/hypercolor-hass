from __future__ import annotations

from typing import Any, cast

import msgspec
from hypercolor.models.device import DeviceConnection, DeviceOrigin, DevicePresentation

from hypercolor.models import (
    ActiveScene,
    Device,
    DeviceZone,
    EffectPreset,
    EffectPresetOrigin,
    EffectSummary,
    LayoutOutput,
    LayoutSummary,
    NormalizedPosition,
    ProfileSummary,
    Scene,
    SpatialLayout,
    Zone,
)

type JsonObject = dict[str, Any]


def effects() -> list[JsonObject]:
    return [
        _model(
            EffectSummary(
                id="rainbow",
                name="Rainbow",
                description="Test rainbow",
                author="Hypercolor",
                category="ambient",
                source="builtin",
                runnable=True,
                version="1.0.0",
                audio_reactive=False,
                tags=["test"],
            )
        ),
        _model(
            EffectSummary(
                id="solid_color",
                name="Solid Color",
                description="Test solid color",
                author="Hypercolor",
                category="static",
                source="builtin",
                runnable=True,
                version="1.0.0",
                audio_reactive=False,
                tags=["test"],
            )
        ),
    ]


def active_effect(
    effect_id: str,
    control_values: dict[str, Any],
    active_preset_id: str | None,
) -> JsonObject:
    payload: JsonObject = {
        "id": effect_id,
        "name": effect_name(effect_id),
        "state": "running" if effect_id else "idle",
        "controls": [
            _wire_control("speed", "Speed", 50.0),
            _wire_control("brightness", "Brightness", 80.0),
        ],
        "control_values": {
            key: {"float": float(value)} if isinstance(value, (int, float)) else value
            for key, value in control_values.items()
        },
        "active_preset_id": active_preset_id,
        "render_group_id": "zone-primary",
        "controls_version": 1,
    }
    if effect_id:
        payload["cover_image_url"] = f"/api/v1/effects/{effect_id}/cover"
    return payload


def device() -> JsonObject:
    return _model(
        Device(
            id="wled-studio",
            layout_device_id="wled:c8c9a33a9091",
            name="WLED - Studio",
            origin=DeviceOrigin(driver_id="wled", backend_id="wled", transport="network"),
            presentation=DevicePresentation(label="WLED", short_label="WLED", icon="lightbulb"),
            status="known",
            brightness=100,
            firmware_version="0.15.0-b3",
            connection=DeviceConnection(
                transport="network",
                endpoint="wled-studio.local",
                ip="10.4.22.169",
                hostname="wled-studio.local",
            ),
            total_leds=275,
            zones=[
                DeviceZone(
                    id="zone_0",
                    name="Main",
                    led_count=275,
                    topology="strip",
                    topology_hint={"type": "strip"},
                )
            ],
        )
    )


def scene() -> JsonObject:
    return _model(Scene(id="default", name="Default"))


def active_scene(effect_id: str) -> JsonObject:
    layout = SpatialLayout(
        id="zone-layout",
        name="Default zone",
        canvas_width=640,
        canvas_height=480,
        zones=[
            LayoutOutput(
                id="wled-studio:zone_0",
                name="WLED - Studio",
                device_id="wled-studio",
                zone_name="zone_0",
                position=NormalizedPosition(x=0.5, y=0.5),
                size=NormalizedPosition(x=1.0, y=1.0),
                rotation=0.0,
                topology={"type": "strip", "count": 275, "direction": "left_to_right"},
            )
        ],
    )
    return _model(
        ActiveScene(
            id="default",
            name="Default",
            priority=50,
            kind="ephemeral",
            groups=[
                Zone(
                    id="zone-primary",
                    name="Default zone",
                    effect_id=effect_id,
                    layout=layout,
                    brightness=1.0,
                    enabled=True,
                    role="primary",
                    controls_version=1,
                )
            ],
            groups_revision=2,
        )
    )


def profile() -> JsonObject:
    return _model(
        ProfileSummary(
            id="profile-default",
            name="Default Profile",
            brightness=80,
            effect_id="rainbow",
            effect_name="Rainbow",
        )
    )


def layout_summary() -> JsonObject:
    return _model(
        LayoutSummary(
            id="default",
            name="Default Layout",
            canvas_width=640,
            canvas_height=480,
            zone_count=1,
            is_active=True,
        )
    )


def layout() -> JsonObject:
    return _model(
        SpatialLayout(
            id="default",
            name="Default Layout",
            canvas_width=640,
            canvas_height=480,
        )
    )


def effect_preset() -> JsonObject:
    return _model(
        EffectPreset(
            id="preset-rainbow",
            name="Rainbow Soft",
            effect_id="rainbow",
            origin=EffectPresetOrigin.BUNDLED,
            editable=False,
            description="A softer bundled look",
            controls={"speed": 60},
            tags=["test"],
        )
    )


def effect_name(effect_id: str) -> str:
    return {"rainbow": "Rainbow", "solid_color": "Solid Color"}.get(effect_id, effect_id)


def _wire_control(control_id: str, name: str, default: float) -> JsonObject:
    return {
        "id": control_id,
        "name": name,
        "kind": "number",
        "control_type": "slider",
        "default_value": {"float": default},
        "min": 0,
        "max": 100,
        "step": 1,
    }


def _model(value: object) -> JsonObject:
    return cast(JsonObject, msgspec.to_builtins(value))
