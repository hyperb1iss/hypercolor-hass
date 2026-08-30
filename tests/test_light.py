from __future__ import annotations

from types import MappingProxyType

from custom_components.hypercolor.light import (
    effect_controls_payload,
    effect_metadata,
    first_id,
)
from custom_components.hypercolor.models import (
    ActiveEffect,
    CatalogIndex,
    EffectLayer,
    control_scalar,
    primary_effect_layer,
)
from hypercolor.models import EffectDetailResponse, EffectSummary, SceneDocument
from tests.support import hypercolor_payloads as payloads
from tests.support.hypercolor_payloads import PRIMARY_LAYER_ID, PRIMARY_ZONE_ID
from tests.support.wire import minimal


def test_catalog_index_makes_duplicate_names_unambiguous() -> None:
    index = CatalogIndex.build([_effect("aurora-v1", "Aurora"), _effect("aurora-v2", "Aurora")])

    assert index.options == ["Aurora (aurora-v1)", "Aurora (aurora-v2)"]
    assert index.resolve("Aurora (aurora-v2)") == "aurora-v2"
    assert index.label("aurora-v1") == "Aurora (aurora-v1)"


def test_catalog_index_keeps_unique_display_name() -> None:
    index = CatalogIndex.build([_effect("neon-rain", "Neon Rain")])

    assert index.options == ["Neon Rain"]
    assert index.resolve("Neon Rain") == "neon-rain"
    assert first_id(index) == "neon-rain"


def test_effect_metadata_projects_catalog_contract() -> None:
    metadata = effect_metadata(_effect("neon-rain", "Neon Rain"))

    assert metadata == {
        "effect_description": "Cascading neon",
        "effect_publisher": "Aurora Labs",
        "effect_audio_reactive": True,
        "effect_tags": ["cyberpunk", "rain"],
        "effect_category": "ambient",
        "effect_version": "1.2.0",
    }


def test_effect_metadata_has_stable_empty_projection() -> None:
    assert effect_metadata(None) == {
        "effect_description": None,
        "effect_publisher": None,
        "effect_audio_reactive": False,
        "effect_tags": [],
        "effect_category": None,
        "effect_version": None,
    }


def test_effect_controls_payload_uses_typed_sdk_controls() -> None:
    detail = EffectDetailResponse.from_dict(
        minimal(
            EffectDetailResponse,
            id="neon-rain",
            name="Neon Rain",
            controls=[
                payloads.wire_control("speed", "Speed", 50.0),
                {
                    "id": "palette",
                    "name": "Palette",
                    "control_type": "dropdown",
                    "default_value": {"kind": "enum", "value": "Sunset"},
                    "labels": ["Sunset", "Ocean"],
                },
            ],
        )
    )
    active = ActiveEffect(
        layer=EffectLayer(
            zone_id=PRIMARY_ZONE_ID,
            layer_id=PRIMARY_LAYER_ID,
            effect_id="neon-rain",
            control_values=MappingProxyType({"speed": {"kind": "float", "value": 72.0}}),
            preset_id=None,
        ),
        detail=detail,
        cover_image_url=None,
    )

    controls = effect_controls_payload(active)

    assert controls[0] == {
        "id": "speed",
        "label": "Speed",
        "kind": "number",
        "min": 0.0,
        "max": 100.0,
        "step": 1.0,
        "value": 72.0,
    }
    assert controls[1]["kind"] == "enum"
    assert controls[1]["options"] == ["Sunset", "Ocean"]
    assert controls[1]["value"] == "Sunset"


def test_primary_effect_layer_prefers_the_primary_zone() -> None:
    custom = payloads.zone("solid_color", {}, None)
    custom["id"] = "zone-custom"
    custom["role"] = "custom"
    display = payloads.zone("clock", {}, None)
    display["id"] = "zone-display"
    display["role"] = "display"
    primary = payloads.zone("rainbow", {"speed": 30.0}, "preset-rainbow")
    scene = SceneDocument.from_dict(payloads.scene_document([display, custom, primary]))

    layer = primary_effect_layer(scene)

    assert layer is not None
    assert layer.zone_id == PRIMARY_ZONE_ID
    assert layer.effect_id == "rainbow"
    assert layer.preset_id == "preset-rainbow"
    assert control_scalar(layer.control_values["speed"]) == 30.0


def test_primary_effect_layer_falls_back_to_the_first_renderable_zone() -> None:
    display = payloads.zone("clock", {}, None)
    display["id"] = "zone-display"
    display["role"] = "display"
    custom = payloads.zone("solid_color", {}, None)
    custom["id"] = "zone-custom"
    custom["role"] = "custom"
    scene = SceneDocument.from_dict(payloads.scene_document([display, custom]))

    layer = primary_effect_layer(scene)

    assert layer is not None
    assert layer.zone_id == "zone-custom"
    assert layer.effect_id == "solid_color"


def test_primary_effect_layer_skips_disabled_layers_and_zones() -> None:
    primary = payloads.zone("rainbow", {}, None)
    primary["layers"][0]["enabled"] = False
    primary["layers"].append(
        {
            "id": "0d6a7c1e-2b3f-4d5e-8f90-a1b2c3d4e5f6",
            "source": {"type": "effect", "effect_id": "solid_color", "controls": {}},
            "enabled": True,
        }
    )
    primary["layers"].append(
        {
            "id": "1e7b8d2f-3c4a-4e6f-9a01-b2c3d4e5f607",
            "source": {"type": "effect", "effect_id": "clock", "controls": {}},
            "enabled": False,
        }
    )
    disabled_zone = payloads.zone("aurora", {}, None)
    disabled_zone["id"] = "zone-dormant"
    disabled_zone["role"] = "custom"
    disabled_zone["enabled"] = False
    scene = SceneDocument.from_dict(payloads.scene_document([disabled_zone, primary]))

    layer = primary_effect_layer(scene)

    assert layer is not None
    assert layer.zone_id == PRIMARY_ZONE_ID
    assert layer.effect_id == "solid_color"

    primary["enabled"] = False
    dormant_only = SceneDocument.from_dict(payloads.scene_document([disabled_zone, primary]))

    assert primary_effect_layer(dormant_only) is None


def test_primary_effect_layer_is_none_for_an_empty_scene() -> None:
    scene = SceneDocument.from_dict(payloads.scene_document([payloads.zone("", {}, None)]))

    assert primary_effect_layer(scene) is None


def _effect(effect_id: str, name: str) -> EffectSummary:
    return EffectSummary.from_dict(
        minimal(
            EffectSummary,
            id=effect_id,
            name=name,
            description="Cascading neon",
            author="Aurora Labs",
            category="ambient",
            source="html",
            runnable=True,
            version="1.2.0",
            audio_reactive=True,
            tags=["cyberpunk", "rain"],
        )
    )
