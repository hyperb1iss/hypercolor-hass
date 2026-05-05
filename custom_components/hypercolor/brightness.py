from __future__ import annotations


def ha_to_daemon(ha_brightness: int) -> int:
    if ha_brightness <= 0:
        return 0
    return max(1, (ha_brightness * 100 + 127) // 255)


def daemon_to_ha(daemon_brightness: int) -> int:
    if daemon_brightness <= 0:
        return 0
    return max(1, (daemon_brightness * 255 + 50) // 100)
