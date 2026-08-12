from __future__ import annotations

from custom_components.hypercolor.light import (
    effect_controls_payload,
    effect_metadata,
    first_id,
)
from custom_components.hypercolor.models import CatalogIndex
from hypercolor.models import ActiveEffect, ControlDefinition, EffectSummary


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
    active = ActiveEffect(
        id="neon-rain",
        name="Neon Rain",
        state="running",
        controls=[
            ControlDefinition(
                id="speed",
                label="Speed",
                type="number",
                default={"float": 50.0},
                min=0,
                max=100,
                step=1,
            ),
            ControlDefinition(
                id="palette",
                label="Palette",
                type="select",
                options=["Sunset", "Ocean"],
            ),
        ],
        control_values={"speed": {"float": 72.0}},
    )

    controls = effect_controls_payload(active)

    assert controls[0] == {
        "id": "speed",
        "label": "Speed",
        "kind": "number",
        "min": 0,
        "max": 100,
        "step": 1,
        "value": 72.0,
    }
    assert controls[1]["kind"] == "enum"
    assert controls[1]["options"] == ["Sunset", "Ocean"]


def _effect(effect_id: str, name: str) -> EffectSummary:
    return EffectSummary(
        id=effect_id,
        name=name,
        description="Cascading neon",
        author="Aurora Labs",
        category="ambient",
        source="builtin",
        runnable=True,
        version="1.2.0",
        audio_reactive=True,
        tags=["cyberpunk", "rain"],
    )
