from __future__ import annotations

from custom_components.hypercolor.light import (
    effect_id_for_name,
    effect_name_for_id,
    effect_names,
    renderable_zones,
)


def test_effect_names_prefer_display_name() -> None:
    catalog = [{"id": "neon_rain", "name": "Neon Rain"}]

    assert effect_names(catalog) == ["Neon Rain"]


def test_effect_names_accept_catalog_payload() -> None:
    catalog = {"effects": [{"id": "neon_rain", "name": "Neon Rain"}]}

    assert effect_names(catalog) == ["Neon Rain"]


def test_effect_id_for_name_maps_home_assistant_choice_to_daemon_id() -> None:
    catalog = [{"id": "neon_rain", "name": "Neon Rain"}]

    assert effect_id_for_name(catalog, "Neon Rain") == "neon_rain"


def test_effect_id_for_name_preserves_unknown_choice() -> None:
    assert effect_id_for_name([], "custom") == "custom"


def test_effect_name_for_id_maps_back_to_display_name() -> None:
    catalog = [{"id": "neon_rain", "name": "Neon Rain"}]

    assert effect_name_for_id(catalog, "neon_rain") == "Neon Rain"
    assert effect_name_for_id(catalog, "unknown") == "unknown"


def test_renderable_zones_excludes_display_faces() -> None:
    state = {
        "zones": [
            {"id": "zone-1", "name": "Desk", "role": "primary"},
            {"id": "zone-2", "name": "Room", "role": "custom"},
            {"id": "zone-3", "name": "LCD", "role": "display"},
        ]
    }

    zones = renderable_zones(state)

    assert [zone["id"] for zone in zones] == ["zone-1", "zone-2"]


def test_renderable_zones_tolerates_missing_state() -> None:
    assert renderable_zones(None) == []
    assert renderable_zones({}) == []
    assert renderable_zones({"zones": "bogus"}) == []
