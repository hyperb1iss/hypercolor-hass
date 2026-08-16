from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, NotRequired, TypedDict

from aiohttp import web

from . import hypercolor_payloads as payloads
from .hypercolor_payloads import JsonObject


class AppliedEffect(TypedDict):
    effect_id: str
    controls: dict[str, Any]
    render_group: NotRequired[str]
    preset_id: NotRequired[str]


class DeviceUpdate(TypedDict):
    device_id: str
    enabled: NotRequired[bool]
    brightness: NotRequired[int]


class ZoneUpdate(TypedDict):
    scene_id: str
    zone_id: str
    brightness: NotRequired[float]
    enabled: NotRequired[bool]


class FakeHypercolorDaemon:
    def __init__(self) -> None:
        self.port = 0
        self.active_effect_id = "rainbow"
        self.active_preset_id: str | None = "preset-rainbow"
        self.active_preset_modified = False
        self.paused = False
        self.brightness = 80
        self.control_values: dict[str, Any] = {"speed": 60.0, "brightness": 80.0}
        self.control_updates: list[dict[str, Any]] = []
        self.applied_effects: list[AppliedEffect] = []
        self.device_updates: list[DeviceUpdate] = []
        self.zone_updates: list[ZoneUpdate] = []
        self.pause_requests = 0
        self.resume_requests = 0
        self.stop_requests = 0

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(protocols=("hypercolor-v1",))
        await ws.prepare(request)
        await ws.send_json(
            {
                "type": "hello",
                "version": "1.0",
                "state": {
                    "active_effect": payloads.effect_name(self.active_effect_id),
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
        parts = request.path.removeprefix("/api/v1/").split("/")
        if (
            request.method == "GET"
            and len(parts) == 3
            and parts[0] == "effects"
            and parts[2] == "presets"
        ):
            presets = [payloads.effect_preset()] if parts[1] == "rainbow" else []
            return self._ok(self._items(presets))
        responses: dict[str, Callable[[], JsonObject]] = {
            "GET /server": self._server,
            "GET /output/power": lambda: {"state": "paused" if self.paused else "running"},
            "POST /diagnose": lambda: {"checks": {}},
            "GET /status": self._status,
            "GET /effects": lambda: self._items(payloads.effects()),
            "GET /effects/active": self._active_effect,
            "GET /devices": lambda: self._items([payloads.device()]),
            "GET /scenes": lambda: self._items([payloads.scene()]),
            "GET /scenes/active": self._active_scene,
            "GET /profiles": lambda: self._items([payloads.profile()]),
            "GET /layouts": lambda: self._items([payloads.layout_summary()]),
            "GET /layouts/active": payloads.layout,
        }
        if response := responses.get(route):
            return self._ok(response())
        return web.json_response({"error": {"code": "not_found", "message": route}}, status=404)

    async def apply_effect(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        effect_id = request.match_info["effect_id"]
        self.active_effect_id = effect_id
        self.active_preset_id = str(body["preset_id"]) if body.get("preset_id") else None
        self.active_preset_modified = False
        self.paused = False
        controls = dict(body.get("controls") or {})
        self.control_values.update(controls)
        applied: AppliedEffect = {"effect_id": effect_id, "controls": controls}
        if render_group := body.get("render_group"):
            applied["render_group"] = str(render_group)
        if preset_id := body.get("preset_id"):
            applied["preset_id"] = str(preset_id)
        self.applied_effects.append(applied)
        return self._ok(
            {
                "effect": {"id": effect_id, "name": payloads.effect_name(effect_id)},
                "applied_controls": controls,
            }
        )

    async def apply_effect_preset(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        effect_id = request.match_info["effect_id"]
        preset_id = request.match_info["preset_id"]
        controls = dict(payloads.effect_preset()["controls"])
        self.active_effect_id = effect_id
        self.active_preset_id = preset_id
        self.active_preset_modified = False
        self.paused = False
        self.control_values.update(controls)
        applied: AppliedEffect = {
            "effect_id": effect_id,
            "controls": controls,
            "preset_id": preset_id,
        }
        if render_group := body.get("render_group"):
            applied["render_group"] = str(render_group)
        self.applied_effects.append(applied)
        return self._ok(
            {
                "effect": {"id": effect_id, "name": payloads.effect_name(effect_id)},
                "applied_controls": controls,
            }
        )

    async def update_controls(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        controls = dict(body.get("controls") or {})
        self.control_values.update(controls)
        self.control_updates.append(controls)
        self.active_preset_modified = self.active_preset_id is not None
        return self._ok({"effect": self.active_effect_id, "applied": controls, "rejected": []})

    async def set_brightness(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.brightness = int(body["brightness"])
        return self._ok({"brightness": self.brightness})

    async def update_device(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.device_updates.append({"device_id": request.match_info["device_id"], **body})
        return self._ok(payloads.device())

    async def stop_effect(self, request: web.Request) -> web.Response:
        self.stop_requests += 1
        if not self.active_effect_id:
            return web.json_response(
                {
                    "error": {
                        "code": "not_found",
                        "message": "No effect is currently active",
                    }
                },
                status=404,
            )
        self.active_effect_id = ""
        self.active_preset_id = None
        self.active_preset_modified = False
        self.paused = False
        return self._ok({"stopped": True})

    async def set_output_power(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.paused = body["state"] == "paused"
        if self.paused:
            self.pause_requests += 1
        else:
            self.resume_requests += 1
        return self._ok({"state": body["state"]})

    async def update_zone(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.zone_updates.append(
            {
                "scene_id": request.match_info["scene_id"],
                "zone_id": request.match_info["zone_id"],
                **body,
            }
        )
        zone = self._active_scene()["groups"][0]
        zone.update(body)
        return self._ok({"zone": zone, "groups_revision": 3})

    def _server(self) -> JsonObject:
        return {
            "instance_id": "srv_e2e",
            "instance_name": "Hyperia",
            "version": "0.1.0",
            "auth_required": False,
            "device_count": 1,
        }

    def _status(self) -> JsonObject:
        return {
            "running": True,
            "version": "0.1.0",
            "server": {
                "instance_id": "srv_e2e",
                "instance_name": "Hyperia",
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
            "render_loop": {
                "state": "paused" if self.paused else "running",
                "fps_tier": "30fps",
                "total_frames": 123,
            },
            "event_bus_subscribers": 1,
            "active_effect": payloads.effect_name(self.active_effect_id),
        }

    def _active_effect(self) -> JsonObject:
        active = payloads.active_effect(
            self.active_effect_id,
            self.control_values,
            self.active_preset_id,
        )
        active["state"] = "paused" if self.paused else "running"
        active["active_preset_modified"] = self.active_preset_modified
        return active

    def _active_scene(self) -> JsonObject:
        return payloads.active_scene(self.active_effect_id)

    @staticmethod
    def _items(items: list[JsonObject]) -> JsonObject:
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
    def _ok(data: JsonObject) -> web.Response:
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


async def _json_body(request: web.Request) -> JsonObject:
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return {}
    return dict(body) if isinstance(body, dict) else {}
