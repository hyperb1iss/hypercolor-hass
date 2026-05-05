from __future__ import annotations

from custom_components.hypercolor.brightness import daemon_to_ha, ha_to_daemon


def test_daemon_values_round_trip_stably() -> None:
    for daemon_value in range(101):
        assert ha_to_daemon(daemon_to_ha(daemon_value)) == daemon_value


def test_ha_values_reach_fixed_point_after_first_round_trip() -> None:
    for ha_value in range(256):
        first = daemon_to_ha(ha_to_daemon(ha_value))
        second = daemon_to_ha(ha_to_daemon(first))
        assert second == first


def test_non_zero_values_do_not_collapse_to_off() -> None:
    assert ha_to_daemon(1) == 1
    assert daemon_to_ha(1) == 3
