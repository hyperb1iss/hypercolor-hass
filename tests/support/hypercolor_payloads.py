from __future__ import annotations

from typing import Any

from hypercolor.models import (
    DeviceOrigin,
    DeviceSummary,
    DiagnoseResponse,
    DriverPresentation,
    EffectDetailResponse,
    EffectPresetSummary,
    EffectSummary,
    LayoutSummary,
    SceneDocument,
    SceneSummary,
    SegmentSummary,
    ServerInfo,
    SpatialLayout,
    SystemStatus,
    ZoneMember,
    ZoneResource,
)

from .wire import JsonObject, minimal

PRIMARY_ZONE_ID = "zone-primary"
PRIMARY_LAYER_ID = "5d1a0a2e-3d7c-4a8c-9a3d-0f1e2b3c4d5e"
COVER_PATH = "/api/v1/effects/{effect_id}/cover"

_EFFECT_NAMES = {"rainbow": "Rainbow", "solid_color": "Solid Color"}


def effects() -> list[JsonObject]:
    return [
        minimal(
            EffectSummary,
            id="rainbow",
            name="Rainbow",
            description="Test rainbow",
            author="Hypercolor",
            category="ambient",
            source="html",
            runnable=True,
            version="1.0.0",
            audio_reactive=False,
            tags=["test"],
        ),
        minimal(
            EffectSummary,
            id="solid_color",
            name="Solid Color",
            description="Test solid color",
            author="Hypercolor",
            category="utility",
            source="html",
            runnable=True,
            version="1.0.0",
            audio_reactive=False,
            tags=["test"],
        ),
    ]


def effect_detail(effect_id: str) -> JsonObject:
    return minimal(
        EffectDetailResponse,
        id=effect_id,
        name=effect_name(effect_id),
        description=f"Test {effect_name(effect_id).lower()}",
        author="Hypercolor",
        category="ambient",
        source="html",
        runnable=True,
        version="1.0.0",
        audio_reactive=False,
        tags=["test"],
        controls=[
            wire_control("speed", "Speed", 50.0),
            wire_control("brightness", "Brightness", 80.0),
        ],
        cover_image_url=COVER_PATH.format(effect_id=effect_id),
    )


def device() -> JsonObject:
    return minimal(
        DeviceSummary,
        id="wled-studio",
        layout_device_id="wled:c8c9a33a9091",
        name="WLED - Studio",
        origin=minimal(DeviceOrigin, driver_id="wled", backend_id="wled", transport="network"),
        presentation=minimal(DriverPresentation, label="WLED", short_label="WLED"),
        status="known",
        brightness=100,
        firmware_version="0.15.0-b3",
        total_leds=275,
        segments=[
            minimal(SegmentSummary, id="zone_0", name="Main", led_count=275, topology="strip"),
        ],
    )


def scene_summary() -> JsonObject:
    return minimal(SceneSummary, id="default", name="Default")


def zone(
    effect_id: str,
    control_values: dict[str, Any],
    preset_id: str | None,
    *,
    brightness: float = 1.0,
    enabled: bool = True,
) -> JsonObject:
    layers: list[JsonObject] = []
    if effect_id:
        source: JsonObject = {
            "type": "effect",
            "effect_id": effect_id,
            "controls": {
                key: value if isinstance(value, dict) else {"kind": "float", "value": float(value)}
                for key, value in control_values.items()
            },
        }
        if preset_id is not None:
            source["preset_id"] = preset_id
        layers.append({"id": PRIMARY_LAYER_ID, "source": source, "enabled": True})
    return minimal(
        ZoneResource,
        id=PRIMARY_ZONE_ID,
        name="Default zone",
        role="primary",
        brightness=brightness,
        enabled=enabled,
        layers=layers,
        members=[
            minimal(
                ZoneMember,
                id="member-1",
                device_id="wled:wled-studio",
                name="WLED - Studio",
                segment="zone_0",
            )
        ],
    )


def scene_document(zones: list[JsonObject], *, revision: int = 2) -> JsonObject:
    return minimal(
        SceneDocument,
        id="default",
        name="Default",
        kind="ephemeral",
        is_default=True,
        revision=revision,
        zones=zones,
        priority=50,
    )


def layout_summary() -> JsonObject:
    return minimal(
        LayoutSummary,
        id="default",
        name="Default Layout",
        canvas_width=640,
        canvas_height=480,
        zone_count=1,
        is_active=True,
    )


def layout() -> JsonObject:
    return minimal(
        SpatialLayout,
        id="default",
        name="Default Layout",
        canvas_width=640,
        canvas_height=480,
        version=1,
    )


def effect_preset() -> JsonObject:
    return minimal(
        EffectPresetSummary,
        id="preset-rainbow",
        name="Rainbow Soft",
        effect_id="rainbow",
        origin="bundled",
        editable=False,
        description="A softer bundled look",
        controls={"speed": {"kind": "float", "value": 60.0}},
        tags=["test"],
    )


def identity() -> JsonObject:
    return minimal(
        ServerInfo,
        instance_id="srv_e2e",
        instance_name="Hyperia",
        version="0.4.0",
        auth_required=False,
        device_count=1,
    )


def system_status(*, active_effect: str | None, brightness: int, paused: bool) -> JsonObject:
    status = minimal(
        SystemStatus,
        running=True,
        version="0.4.0",
        device_count=1,
        effect_count=2,
        scene_count=1,
        global_brightness=brightness,
        audio_available=True,
        capture_available=False,
        uptime_seconds=42,
        event_bus_subscribers=1,
        active_effect=active_effect,
        active_scene="Default",
    )
    status["render_loop"].update(
        {"state": "paused" if paused else "running", "fps_tier": "30fps", "total_frames": 123}
    )
    return status


def diagnostics() -> JsonObject:
    return minimal(DiagnoseResponse)


def effect_name(effect_id: str) -> str:
    return _EFFECT_NAMES.get(effect_id, effect_id)


def wire_control(control_id: str, name: str, default: float) -> JsonObject:
    return {
        "id": control_id,
        "name": name,
        "control_type": "slider",
        "default_value": {"kind": "float", "value": default},
        "min": 0,
        "max": 100,
        "step": 1,
    }
