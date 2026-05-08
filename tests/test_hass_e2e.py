from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, State
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hypercolor.const import (
    CONF_API_KEY,
    CONF_CHANNELS_AUDIO,
    CONF_CHANNELS_METRICS,
    CONF_LIVE_CONTROLS_ENABLED,
    CONF_PER_DEVICE_ENTITIES,
    CONF_RECONCILE_INTERVAL_S,
    DOMAIN,
    OPTIONS_DEFAULTS,
)
from custom_components.hypercolor.services import CONF_CONFIG_ENTRY_ID, SERVICE_SET_COLOR


@pytest.fixture
async def fake_daemon(
    unused_tcp_port_factory: Callable[[], int],
    socket_enabled: None,
) -> AsyncIterator[_FakeHypercolorDaemon]:
    daemon = _FakeHypercolorDaemon()
    app = web.Application()
    app.router.add_get("/api/v1/ws", daemon.websocket)
    app.router.add_post("/api/v1/effects/{effect_id}/apply", daemon.apply_effect)
    app.router.add_patch("/api/v1/effects/current/controls", daemon.update_controls)
    app.router.add_put("/api/v1/settings/brightness", daemon.set_brightness)
    app.router.add_put("/api/v1/devices/{device_id}", daemon.update_device)
    app.router.add_post("/api/v1/effects/stop", daemon.stop_effect)
    app.router.add_route("*", "/api/v1/{tail:.*}", daemon.handle_api)
    runner = web.AppRunner(app)
    await runner.setup()
    daemon.port = unused_tcp_port_factory()
    site = web.TCPSite(runner, "127.0.0.1", daemon.port)
    await site.start()
    try:
        yield daemon
    finally:
        await runner.cleanup()


async def test_config_entry_boots_and_controls_fake_daemon(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    fake_daemon: _FakeHypercolorDaemon,
) -> None:
    entry = await _setup_entry(hass, port=fake_daemon.port)

    master = _first_state(hass, "light", lambda state: state.attributes.get("effect") == "Rainbow")
    assert master.state == "on"
    assert master.attributes["active_effect_id"] == "rainbow"
    assert (
        master.attributes["active_effect_cover_image_url"]
        == f"http://127.0.0.1:{fake_daemon.port}/api/v1/effects/active/cover"
    )
    assert (
        master.attributes["effect_image"]
        == f"http://127.0.0.1:{fake_daemon.port}/api/v1/effects/active/cover"
    )
    assert "Solid Color" in master.attributes["effect_list"]

    speed = _first_state(hass, "number", lambda state: "speed" in state.entity_id)
    assert float(speed.state) == 60.0

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": speed.entity_id, "value": 35},
        blocking=True,
    )

    assert fake_daemon.control_updates[-1] == {"speed": 35.0}

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": master.entity_id, "effect": "Solid Color"},
        blocking=True,
    )

    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "solid_color",
        "controls": {},
    }

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_COLOR,
        {
            CONF_CONFIG_ENTRY_ID: entry.entry_id,
            "hex": "#80ff00",
        },
        blocking=True,
    )

    assert fake_daemon.applied_effects[-1] == {
        "effect_id": "solid_color",
        "controls": {"color": "#80ff00"},
    }
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.e2e
@pytest.mark.skipif(
    os.environ.get("HYPERCOLOR_HASS_REAL_E2E") != "1",
    reason="set HYPERCOLOR_HASS_REAL_E2E=1 to use a running local daemon",
)
async def test_real_daemon_config_entry_boots(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    socket_enabled: None,
) -> None:
    entry = await _setup_entry(
        hass,
        host=os.environ.get("HYPERCOLOR_HOST", "127.0.0.1"),
        port=int(os.environ.get("HYPERCOLOR_PORT", "9420")),
    )

    master = _first_state(hass, "light", lambda state: bool(state.attributes.get("effect_list")))
    assert master.state in {"on", "off"}
    assert master.attributes["effect_list"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def _setup_entry(
    hass: HomeAssistant,
    *,
    host: str = "127.0.0.1",
    port: int,
) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Hypercolor E2E",
        unique_id="srv_e2e",
        data={
            CONF_HOST: host,
            CONF_PORT: port,
            CONF_API_KEY: None,
        },
        options={
            **OPTIONS_DEFAULTS,
            CONF_RECONCILE_INTERVAL_S: 3600,
            CONF_CHANNELS_AUDIO: False,
            CONF_CHANNELS_METRICS: False,
            CONF_LIVE_CONTROLS_ENABLED: True,
            CONF_PER_DEVICE_ENTITIES: ["wled-studio"],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _first_state(
    hass: HomeAssistant,
    domain: str,
    predicate: Callable[[State], bool],
) -> State:
    for state in hass.states.async_all(domain):
        if predicate(state):
            return state
    msg = f"No {domain} entity matched predicate"
    raise AssertionError(msg)


class _FakeHypercolorDaemon:
    def __init__(self) -> None:
        self.port = 0
        self.active_effect_id = "rainbow"
        self.brightness = 80
        self.control_values: dict[str, Any] = {"speed": 60.0, "brightness": 80.0}
        self.control_updates: list[dict[str, Any]] = []
        self.applied_effects: list[dict[str, Any]] = []
        self.device_updates: list[dict[str, Any]] = []

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(protocols=("hypercolor-v1",))
        await ws.prepare(request)
        await ws.send_json(
            {
                "type": "hello",
                "version": "1.0",
                "state": {
                    "active_effect": self._active_effect()["name"],
                    "active_effect_id": self.active_effect_id,
                    "global_brightness": self.brightness,
                    "device_count": 1,
                    "scene_count": 1,
                },
                "capabilities": ["events"],
                "subscriptions": [],
            }
        )
        async for message in ws:
            if message.type == web.WSMsgType.TEXT:
                await ws.send_json({"type": "subscribed", "channels": ["events"]})
        return ws

    async def handle_api(self, request: web.Request) -> web.Response:
        route = f"{request.method} {request.path.removeprefix('/api/v1')}"
        responses = {
            "GET /server": self._server,
            "GET /status": self._status,
            "GET /effects": lambda: self._items(self._effects()),
            "GET /effects/active": self._active_effect,
            "GET /devices": lambda: self._items([self._device()]),
            "GET /scenes": lambda: self._items([self._scene()]),
            "GET /scenes/active": self._scene,
            "GET /profiles": lambda: self._items([self._profile()]),
            "GET /layouts": lambda: self._items([self._layout_summary()]),
            "GET /layouts/active": self._layout,
            "GET /library/presets": lambda: self._items([self._preset()]),
        }
        if response := responses.get(route):
            return self._ok(response())
        return web.json_response({"error": {"code": "not_found", "message": route}}, status=404)

    async def apply_effect(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        effect_id = request.match_info["effect_id"]
        self.active_effect_id = effect_id
        controls = dict(body.get("controls") or {})
        self.control_values.update(controls)
        self.applied_effects.append({"effect_id": effect_id, "controls": controls})
        return self._ok(
            {
                "effect": {"id": effect_id, "name": self._effect_name(effect_id)},
                "applied_controls": controls,
            }
        )

    async def update_controls(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        controls = dict(body.get("controls") or {})
        self.control_values.update(controls)
        self.control_updates.append(controls)
        return self._ok({"effect": self.active_effect_id, "applied": controls, "rejected": []})

    async def set_brightness(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.brightness = int(body["brightness"])
        return self._ok({"brightness": self.brightness})

    async def update_device(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.device_updates.append({"device_id": request.match_info["device_id"], **body})
        return self._ok(self._device())

    async def stop_effect(self, request: web.Request) -> web.Response:
        self.active_effect_id = ""
        return self._ok({"stopped": True})

    def _server(self) -> dict[str, Any]:
        return {
            "instance_id": "srv_e2e",
            "instance_name": "Hypercolor E2E",
            "version": "0.1.0",
            "auth_required": False,
            "device_count": 1,
        }

    def _status(self) -> dict[str, Any]:
        return {
            "running": True,
            "version": "0.1.0",
            "server": {
                "instance_id": "srv_e2e",
                "instance_name": "Hypercolor E2E",
                "version": "0.1.0",
            },
            "config_path": "/var/lib/hypercolor/config.toml",
            "data_dir": "/var/lib/hypercolor",
            "cache_dir": "/var/cache/hypercolor",
            "uptime_seconds": 42,
            "device_count": 1,
            "effect_count": 2,
            "scene_count": 1,
            "global_brightness": self.brightness,
            "audio_available": True,
            "capture_available": False,
            "render_loop": {"state": "running", "fps_tier": "30fps", "total_frames": 123},
            "event_bus_subscribers": 1,
            "active_effect": self._effect_name(self.active_effect_id),
        }

    def _effects(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "rainbow",
                "name": "Rainbow",
                "description": "Test rainbow",
                "author": "Hypercolor",
                "category": "ambient",
                "source": "builtin",
                "runnable": True,
                "version": "1.0.0",
                "audio_reactive": False,
                "tags": ["test"],
            },
            {
                "id": "solid_color",
                "name": "Solid Color",
                "description": "Test solid color",
                "author": "Hypercolor",
                "category": "static",
                "source": "builtin",
                "runnable": True,
                "version": "1.0.0",
                "audio_reactive": False,
                "tags": ["test"],
            },
        ]

    def _active_effect(self) -> dict[str, Any]:
        effect = {
            "id": self.active_effect_id,
            "name": self._effect_name(self.active_effect_id),
            "state": "running",
            "controls": [
                {
                    "id": "speed",
                    "label": "Speed",
                    "type": "number",
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "default": 50,
                    "value": self.control_values.get("speed"),
                },
                {
                    "id": "brightness",
                    "label": "Brightness",
                    "type": "number",
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "default": 80,
                    "value": self.control_values.get("brightness"),
                },
            ],
            "control_values": self.control_values,
            "active_preset_id": "preset-rainbow",
        }
        if self.active_effect_id:
            effect["cover_image_url"] = f"/api/v1/effects/{self.active_effect_id}/cover"
        return effect

    def _device(self) -> dict[str, Any]:
        return {
            "id": "wled-studio",
            "layout_device_id": "wled:c8c9a33a9091",
            "name": "WLED - Studio",
            "origin": {
                "driver_id": "wled",
                "backend_id": "wled",
                "transport": "network",
            },
            "presentation": {
                "label": "WLED",
                "short_label": "WLED",
                "icon": "lightbulb",
            },
            "status": "known",
            "brightness": 100,
            "firmware_version": "0.15.0-b3",
            "connection": {
                "transport": "network",
                "endpoint": "wled-studio.local",
                "ip": "10.4.22.169",
                "hostname": "wled-studio.local",
            },
            "total_leds": 275,
            "zones": [
                {
                    "id": "zone_0",
                    "name": "Main",
                    "led_count": 275,
                    "topology": "strip",
                    "topology_hint": {"type": "strip"},
                }
            ],
        }

    @staticmethod
    def _scene() -> dict[str, Any]:
        return {"id": "default", "name": "Default", "description": None, "enabled": True}

    @staticmethod
    def _profile() -> dict[str, Any]:
        return {
            "id": "profile-default",
            "name": "Default Profile",
            "description": None,
            "brightness": 80,
            "effect_id": "rainbow",
            "effect_name": "Rainbow",
        }

    @staticmethod
    def _layout_summary() -> dict[str, Any]:
        return {
            "id": "default",
            "name": "Default Layout",
            "canvas_width": 640,
            "canvas_height": 480,
            "zone_count": 1,
            "is_active": True,
        }

    @staticmethod
    def _layout() -> dict[str, Any]:
        return {
            "id": "default",
            "name": "Default Layout",
            "canvas_width": 640,
            "canvas_height": 480,
            "zones": [],
        }

    @staticmethod
    def _preset() -> dict[str, Any]:
        return {
            "id": "preset-rainbow",
            "name": "Rainbow Soft",
            "effect_id": "rainbow",
            "controls": {"speed": 60},
            "tags": ["test"],
        }

    @staticmethod
    def _items(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "items": items,
            "pagination": {
                "offset": 0,
                "limit": 50,
                "total": len(items),
                "has_more": False,
            },
        }

    @staticmethod
    def _effect_name(effect_id: str) -> str:
        return {"rainbow": "Rainbow", "solid_color": "Solid Color"}.get(effect_id, effect_id)

    @staticmethod
    def _ok(data: dict[str, Any]) -> web.Response:
        return web.json_response(
            {
                "data": data,
                "meta": {
                    "api_version": "1.0",
                    "request_id": "req_e2e",
                    "timestamp": "2026-05-05T00:00:00Z",
                },
            }
        )


async def _json_body(request: web.Request) -> dict[str, Any]:
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return {}
    return dict(body) if isinstance(body, dict) else {}
