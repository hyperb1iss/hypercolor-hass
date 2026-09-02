from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, NotRequired, TypedDict

from aiohttp import web

from . import hypercolor_payloads as payloads
from .hypercolor_payloads import PRIMARY_ZONE_ID, JsonObject

_SCALAR_KINDS = {"bool", "int", "float", "text"}


class AppliedEffect(TypedDict):
    effect_id: str
    controls: dict[str, Any]
    zone: NotRequired[str]
    preset_id: NotRequired[str]


class DeviceUpdate(TypedDict):
    device_id: str
    enabled: NotRequired[bool]
    brightness: NotRequired[int]


class ZoneUpdate(TypedDict):
    zone_id: str
    brightness: NotRequired[float]
    enabled: NotRequired[bool]
    name: NotRequired[str]


class FakeHypercolorDaemon:
    """Serve the slice of the daemon contract the integration consumes."""

    def __init__(self) -> None:
        self.port = 0
        self.active_effect_id = "rainbow"
        self.active_preset_id: str | None = "preset-rainbow"
        self.paused = False
        self.brightness = 0.8
        self.zone_brightness = 1.0
        self.zone_enabled = True
        self.control_values: dict[str, Any] = {
            "speed": payloads.envelope(60.0),
            "brightness": payloads.envelope(80.0),
        }
        self.control_updates: list[dict[str, Any]] = []
        self.applied_effects: list[AppliedEffect] = []
        self.scenes: list[JsonObject] = [payloads.scene_summary()]
        self.effects: list[JsonObject] = payloads.effects()
        self.activated_scenes: list[str] = []
        self.device_updates: list[DeviceUpdate] = []
        self.zone_updates: list[ZoneUpdate] = []
        self.pause_requests = 0
        self.resume_requests = 0
        self.clear_requests = 0

    @property
    def scalar_control_values(self) -> dict[str, Any]:
        """The live layer's controls, flattened for assertions."""
        return _scalar_controls(self.control_values)

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(protocols=("hypercolor-v1",))
        await ws.prepare(request)
        await ws.send_json(
            {
                "type": "hello",
                "version": "1.0",
                "state": {},
                "capabilities": ["events", "commands"],
                "subscriptions": [],
            }
        )
        async for message in ws:
            if message.type == web.WSMsgType.TEXT:
                await ws.send_json({"type": "subscribed", "topics": [{"topic": "events"}]})
        return ws

    async def handle_api(self, request: web.Request) -> web.Response:
        route = f"{request.method} {request.path.removeprefix('/api/v1')}"
        parts = request.path.removeprefix("/api/v1/").split("/")
        if request.method == "GET" and len(parts) == 2 and parts[0] == "effects":
            return self._ok(payloads.effect_detail(parts[1]))
        if (
            request.method == "GET"
            and len(parts) == 3
            and parts[0] == "effects"
            and parts[2] == "presets"
        ):
            presets = [payloads.effect_preset()] if parts[1] == "rainbow" else []
            return self._ok(self._complete(presets))
        responses: dict[str, Callable[[], JsonObject]] = {
            "GET /system": self._system,
            "GET /output": self._output,
            "POST /diagnose": payloads.diagnostics,
            "GET /effects": lambda: self._complete(list(self.effects)),
            "GET /devices": lambda: self._paged([payloads.device()], request),
            "GET /scene": self._scene,
            "GET /scenes": lambda: self._complete(list(self.scenes)),
            "GET /layouts": lambda: self._paged([payloads.layout_summary()], request),
            "GET /layouts/active": payloads.layout,
            "GET /system/audio-devices": payloads.audio_devices,
        }
        if response := responses.get(route):
            return self._ok(response())
        return web.json_response({"error": {"code": "not_found", "message": route}}, status=404)

    async def activate_scene(self, request: web.Request) -> web.Response:
        scene_id = request.match_info["scene_id"]
        scene = next((item for item in self.scenes if item["id"] == scene_id), None)
        if scene is None:
            return web.json_response(
                {"error": {"code": "not_found", "message": scene_id}},
                status=404,
            )
        self.activated_scenes.append(scene_id)
        return self._ok(payloads.activate_scene_response(scene_id, str(scene["name"])))

    async def apply_effect(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        effect_id = request.match_info["effect_id"]
        controls = dict(body.get("controls") or {})
        self.active_effect_id = effect_id
        self.active_preset_id = str(body["preset_id"]) if body.get("preset_id") else None
        self.paused = False
        self.control_values.update(controls)
        applied: AppliedEffect = {"effect_id": effect_id, "controls": _scalar_controls(controls)}
        if zone := body.get("zone"):
            applied["zone"] = str(zone)
        if preset_id := body.get("preset_id"):
            applied["preset_id"] = str(preset_id)
        self.applied_effects.append(applied)
        return self._ok(self._apply_response())

    async def apply_effect_preset(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        effect_id = request.match_info["effect_id"]
        preset_id = request.match_info["preset_id"]
        controls = dict(payloads.effect_preset()["controls"])
        self.active_effect_id = effect_id
        self.active_preset_id = preset_id
        self.paused = False
        self.control_values.update(controls)
        applied: AppliedEffect = {
            "effect_id": effect_id,
            "controls": _scalar_controls(controls),
            "preset_id": preset_id,
        }
        if zone := body.get("zone"):
            applied["zone"] = str(zone)
        self.applied_effects.append(applied)
        return self._ok(self._apply_response())

    async def patch_layer_controls(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        controls = dict(body.get("values") or {})
        self.control_values.update(controls)
        self.control_updates.append(
            {
                "zone": request.match_info["zone"],
                "layer": request.match_info["layer"],
                "values": _scalar_controls(controls),
            }
        )
        return self._ok(self._zone())

    async def patch_output(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        if "brightness" in body:
            self.brightness = float(body["brightness"])
        if "power" in body:
            self.paused = body["power"] == "paused"
            if self.paused:
                self.pause_requests += 1
            else:
                self.resume_requests += 1
        return self._ok(self._output())

    async def update_device(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.device_updates.append({"device_id": request.match_info["device_id"], **body})
        return self._ok(payloads.device())

    async def clear_scene(self, request: web.Request) -> web.Response:
        self.clear_requests += 1
        self.active_effect_id = ""
        self.active_preset_id = None
        return self._ok(self._scene())

    async def update_zone(self, request: web.Request) -> web.Response:
        body = await _json_body(request)
        self.zone_updates.append({"zone_id": request.match_info["zone"], **body})
        if "brightness" in body:
            self.zone_brightness = float(body["brightness"])
        if "enabled" in body:
            self.zone_enabled = bool(body["enabled"])
        return self._ok(self._zone())

    def _system(self) -> JsonObject:
        return {
            "identity": payloads.identity(),
            "status": payloads.system_status(
                active_effect=(
                    payloads.effect_name(self.active_effect_id) if self.active_effect_id else None
                ),
                brightness=round(self.brightness * 100),
                paused=self.paused,
            ),
        }

    def _output(self) -> JsonObject:
        return {"power": "paused" if self.paused else "running", "brightness": self.brightness}

    def _zone(self) -> JsonObject:
        return payloads.zone(
            self.active_effect_id,
            self.control_values,
            self.active_preset_id,
            brightness=self.zone_brightness,
            enabled=self.zone_enabled,
        )

    def _scene(self) -> JsonObject:
        return payloads.scene_document([self._zone()])

    def _apply_response(self) -> JsonObject:
        return {
            "zone": self._zone(),
            "transition": {"type": "cut"},
            "output": {"applied": True},
        }

    @staticmethod
    def _complete(items: list[JsonObject]) -> JsonObject:
        """A list the daemon serves whole: no page block at all."""
        return {"items": items, "total": len(items)}

    @staticmethod
    def _paged(items: list[JsonObject], request: web.Request) -> JsonObject:
        """A genuinely paged list, echoing the offset and limit it was asked for."""
        offset = int(request.query.get("offset", 0))
        limit = int(request.query.get("limit", 50))
        window = items[offset : offset + limit]
        return {
            "items": window,
            "total": len(items),
            "page": {"offset": offset, "limit": limit, "has_more": offset + limit < len(items)},
        }

    @staticmethod
    def _ok(data: JsonObject) -> web.Response:
        return web.json_response(
            {
                "data": data,
                "meta": {
                    "api_version": "1.0",
                    "request_id": "req_e2e",
                    "timestamp": "2026-08-29T00:00:00Z",
                },
            }
        )


def _scalar_controls(controls: dict[str, Any]) -> dict[str, Any]:
    """Flatten canonical control envelopes the way an assertion wants to read them."""
    flattened: dict[str, Any] = {}
    for key, value in controls.items():
        if isinstance(value, dict) and value.get("kind") in _SCALAR_KINDS:
            flattened[key] = value.get("value")
        else:
            flattened[key] = value
    return flattened


async def _json_body(request: web.Request) -> JsonObject:
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return {}
    return dict(body) if isinstance(body, dict) else {}


__all__ = ["PRIMARY_ZONE_ID", "FakeHypercolorDaemon"]
