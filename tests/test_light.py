from __future__ import annotations

from custom_components.hypercolor.light import effect_id_for_name, effect_names


def test_effect_names_prefer_display_name() -> None:
    catalog = [{"id": "neon_rain", "name": "Neon Rain"}]

    assert effect_names(catalog) == ["Neon Rain"]


def test_effect_id_for_name_maps_home_assistant_choice_to_daemon_id() -> None:
    catalog = [{"id": "neon_rain", "name": "Neon Rain"}]

    assert effect_id_for_name(catalog, "Neon Rain") == "neon_rain"


def test_effect_id_for_name_preserves_unknown_choice() -> None:
    assert effect_id_for_name([], "custom") == "custom"
