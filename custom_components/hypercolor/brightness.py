from __future__ import annotations


def ha_to_daemon(ha_brightness: int) -> int:
    """Map Home Assistant 0-255 onto the daemon's 0-100 device percent."""
    if ha_brightness <= 0:
        return 0
    return max(1, (ha_brightness * 100 + 127) // 255)


def daemon_to_ha(daemon_brightness: int) -> int:
    """Map the daemon's 0-100 device percent onto Home Assistant 0-255."""
    if daemon_brightness <= 0:
        return 0
    return max(1, (daemon_brightness * 255 + 50) // 100)


def ha_to_fraction(ha_brightness: int) -> float:
    """Map Home Assistant 0-255 onto the 0.0-1.0 output and zone scale."""
    if ha_brightness <= 0:
        return 0.0
    return round(min(ha_brightness, 255) / 255, 4)


def fraction_to_ha(fraction: float) -> int:
    """Map the 0.0-1.0 output and zone scale onto Home Assistant 0-255."""
    return max(0, min(255, round(fraction * 255)))
