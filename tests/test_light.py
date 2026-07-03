from __future__ import annotations

from custom_components.hypercolor.light import (
    active_effect_entry,
    effect_controls_payload,
    effect_id_for_name,
    effect_metadata,
    effect_name_for_id,
    effect_names,
    first_effect_id,
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


def test_first_effect_id_returns_leading_catalog_id() -> None:
    catalog = [{"id": "neon_rain", "name": "Neon Rain"}, {"id": "aurora", "name": "Aurora"}]

    assert first_effect_id(catalog) == "neon_rain"


def test_first_effect_id_handles_empty_catalog() -> None:
    assert first_effect_id([]) is None
    assert first_effect_id(None) is None


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


def _catalog() -> dict[str, list[dict[str, object]]]:
    return {
        "effects": [
            {
                "id": "neon_rain",
                "name": "Neon Rain",
                "description": "Cascading neon",
                "author": "Aurora Labs",
                "category": "ambient",
                "version": "1.2.0",
                "audio_reactive": True,
                "tags": ["cyberpunk", "rain"],
            },
            {"id": "aurora", "name": "Aurora"},
        ]
    }


def test_active_effect_entry_matches_by_id_then_name() -> None:
    catalog = _catalog()

    by_id = active_effect_entry(catalog, "neon_rain", None)
    by_name = active_effect_entry(catalog, None, "Aurora")
    assert by_id is not None
    assert by_id["name"] == "Neon Rain"
    assert by_name is not None
    assert by_name["id"] == "aurora"
    assert active_effect_entry(catalog, "missing", "missing") is None
    assert active_effect_entry([], "neon_rain", None) is None


def test_effect_metadata_reads_catalog_record() -> None:
    entry = _catalog()["effects"][0]

    metadata = effect_metadata(entry, active_detail=None)

    assert metadata["description"] == "Cascading neon"
    assert metadata["publisher"] == "Aurora Labs"
    assert metadata["category"] == "ambient"
    assert metadata["version"] == "1.2.0"
    assert metadata["audio_reactive"] is True
    assert metadata["tags"] == ["cyberpunk", "rain"]


def test_effect_metadata_prefers_live_audio_flag_and_tolerates_gaps() -> None:
    # Live detail overrides the catalog flag; missing catalog stays safe.
    assert (
        effect_metadata({"audio_reactive": False}, {"audio_reactive": True})["audio_reactive"]
        is True
    )
    empty = effect_metadata(None, None)
    assert empty == {
        "description": None,
        "publisher": None,
        "audio_reactive": False,
        "tags": [],
        "category": None,
        "version": None,
    }


def test_effect_controls_payload_normalizes_descriptors() -> None:
    active_detail = {
        "controls": [
            {
                "id": "speed",
                "name": "Speed",
                "kind": "number",
                "control_type": "slider",
                "min": 0,
                "max": 100,
                "step": 1,
                "default_value": {"float": 50.0},
            },
            {
                "id": "palette",
                "name": "Palette",
                "kind": "enum",
                "options": [{"id": "sunset", "label": "Sunset"}, "Ocean"],
            },
        ],
        "control_values": {"speed": {"float": 72.0}},
    }

    controls = effect_controls_payload(active_detail)

    assert controls[0] == {
        "id": "speed",
        "label": "Speed",
        "kind": "number",
        "min": 0,
        "max": 100,
        "step": 1,
        "value": 72.0,
    }
    assert controls[1]["value"] is None
    assert controls[1]["options"] == ["Sunset", "Ocean"]


def test_effect_controls_payload_canonicalizes_kind_from_legacy_type() -> None:
    # The real client normalizes daemon controls to a legacy `type` string and
    # ships dropdown choices under `labels`; the payload must handle both.
    active_detail = {
        "controls": [
            {"id": "brightness", "label": "Brightness", "type": "number", "min": 0, "max": 100},
            {"id": "mirror", "label": "Mirror", "type": "boolean", "value": True},
            {"id": "tint", "label": "Tint", "type": "color", "value": {"color": [1.0, 0.0, 0.5]}},
            {
                "id": "palette",
                "label": "Palette",
                "type": "select",
                "labels": ["Sunset", "Ocean"],
                "value": "Ocean",
            },
            {"id": "caption", "label": "Caption", "type": "text", "value": "hi"},
        ],
    }

    controls = effect_controls_payload(active_detail)
    by_id = {control["id"]: control for control in controls}

    assert by_id["brightness"]["kind"] == "number"
    assert by_id["mirror"]["kind"] == "boolean"
    assert by_id["tint"]["kind"] == "color"
    assert by_id["palette"]["kind"] == "enum"
    assert by_id["palette"]["options"] == ["Sunset", "Ocean"]
    # Controls with no faithful card widget are marked `other` (card skips them).
    assert by_id["caption"]["kind"] == "other"


def test_effect_controls_payload_reads_generated_bound_aliases() -> None:
    # The generated client model names bounds `min_`/`max_`.
    control = {"id": "speed", "label": "Speed", "control_type": "slider", "min_": 5, "max_": 90}
    payload = effect_controls_payload({"controls": [control]})
    assert payload[0]["kind"] == "number"
    assert payload[0]["min"] == 5
    assert payload[0]["max"] == 90


def test_effect_controls_payload_tolerates_missing_controls() -> None:
    assert effect_controls_payload(None) == []
    assert effect_controls_payload({"controls": "bogus"}) == []
