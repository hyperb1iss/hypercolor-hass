from __future__ import annotations

from custom_components.hypercolor.binary_sensor import active_effect_audio_reactive


def test_active_effect_audio_reactive_reads_catalog_metadata() -> None:
    state = {"active_effect": "Aurora", "active_effect_id": "aurora"}
    catalog = {"effects": [{"id": "aurora", "name": "Aurora", "audio_reactive": True}]}

    assert active_effect_audio_reactive(state, catalog) is True


def test_active_effect_audio_reactive_prefers_live_state_when_present() -> None:
    state = {
        "active_effect": "Aurora",
        "active_effect_id": "aurora",
        "active_effect_detail": {"audio_reactive": False},
    }
    catalog = {"effects": [{"id": "aurora", "name": "Aurora", "audio_reactive": True}]}

    assert active_effect_audio_reactive(state, catalog) is False


def test_active_effect_audio_reactive_prefers_id_over_ambiguous_name() -> None:
    state = {"active_effect": "Aurora", "active_effect_id": "aurora-v2"}
    catalog = {
        "effects": [
            {"id": "aurora-v1", "name": "Aurora", "audio_reactive": False},
            {"id": "aurora-v2", "name": "Aurora", "audio_reactive": True},
        ]
    }

    assert active_effect_audio_reactive(state, catalog) is True
