from __future__ import annotations

from types import SimpleNamespace

from custom_components.hypercolor.select import HypercolorPresetSelect, _preset_option_map


def test_preset_options_keep_one_label_for_unique_names() -> None:
    bundled = SimpleNamespace(
        id="preset-bundled",
        name="Soft",
        effect_id="aurora",
        origin="bundled",
        editable=False,
    )

    assert _preset_option_map([bundled]) == {"Soft": bundled}


def test_preset_options_disambiguate_bundled_and_saved_names() -> None:
    bundled = SimpleNamespace(id="preset-bundled", name="Soft", origin="bundled")
    saved = SimpleNamespace(id="preset-saved", name="Soft", origin="saved")

    assert _preset_option_map([bundled, saved]) == {
        "Soft (Built-in)": bundled,
        "Soft (Saved)": saved,
    }


def test_preset_options_hide_stack_from_stale_effect() -> None:
    preset = SimpleNamespace(id="preset-bundled", name="Soft", origin="bundled")
    entity = object.__new__(HypercolorPresetSelect)
    entity.coordinator = SimpleNamespace(data={"preset_effect_id": "aurora", "presets": [preset]})
    entity._state = SimpleNamespace(data={"active_effect_id": "rainbow"})

    assert entity.options == []
