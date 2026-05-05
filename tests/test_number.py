from __future__ import annotations

from custom_components.hypercolor.number import _normalize


def test_live_control_names_normalize_to_static_ids() -> None:
    assert _normalize("Hue Shift") == "hue_shift"
    assert _normalize("Effect Speed") == "effect_speed"
