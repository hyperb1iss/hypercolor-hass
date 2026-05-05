from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "hypercolor"
NAME = "Hypercolor"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9420
DEFAULT_RECONCILE_INTERVAL_S = 60
DEFAULT_DISCONNECT_GRACE_S = 5
DEFAULT_UNAVAILABLE_AFTER_S = 30
DEFAULT_AUDIO_BEAT_HOLD_MS = 100

CONF_API_KEY = "api_key"
CONF_CHANNELS_AUDIO = "channels.audio"
CONF_CHANNELS_DEVICE_METRICS = "channels.device_metrics"
CONF_CHANNELS_METRICS = "channels.metrics"
CONF_DISCONNECT_GRACE_S = "disconnect_grace_s"
CONF_LIVE_CONTROLS_ENABLED = "live_controls_enabled"
CONF_PER_DEVICE_ENTITIES = "per_device_entities"
CONF_RECONCILE_INTERVAL_S = "reconcile_interval_s"
CONF_UNAVAILABLE_AFTER_S = "unavailable_after_s"
CONF_AUDIO_BEAT_HOLD_MS = "audio_beat_hold_ms"

PLATFORMS = [
    Platform.LIGHT,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.NUMBER,
]

LIVE_CONTROL_IDS = ("brightness", "speed", "hue_shift", "intensity")

OPTIONS_DEFAULTS = {
    CONF_RECONCILE_INTERVAL_S: DEFAULT_RECONCILE_INTERVAL_S,
    CONF_CHANNELS_AUDIO: False,
    CONF_CHANNELS_METRICS: False,
    CONF_CHANNELS_DEVICE_METRICS: False,
    CONF_PER_DEVICE_ENTITIES: [],
    CONF_LIVE_CONTROLS_ENABLED: True,
    CONF_AUDIO_BEAT_HOLD_MS: DEFAULT_AUDIO_BEAT_HOLD_MS,
    CONF_DISCONNECT_GRACE_S: DEFAULT_DISCONNECT_GRACE_S,
    CONF_UNAVAILABLE_AFTER_S: DEFAULT_UNAVAILABLE_AFTER_S,
}

TO_REDACT = {
    CONF_API_KEY,
    "api_keys",
    "bearer",
    "external_host",
    "host",
    "ip",
    "ip_address",
    "mac",
    "mac_address",
    "password",
    "token",
    "url",
}
