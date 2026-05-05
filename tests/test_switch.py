from __future__ import annotations

from custom_components.hypercolor.switch import audio_device_enabled


def test_audio_device_enabled_uses_daemon_none_sentinel() -> None:
    assert audio_device_enabled("default") is True
    assert audio_device_enabled("none") is False
    assert audio_device_enabled("") is False
    assert audio_device_enabled(None) is None
