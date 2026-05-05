from __future__ import annotations

from scripts.hass_dev import CONFIGURATION


def test_dev_hass_config_is_localhost_only() -> None:
    assert "server_host: 127.0.0.1" in CONFIGURATION
    assert "server_port: 8123" in CONFIGURATION
    assert "custom_components.hypercolor: debug" in CONFIGURATION
