from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from aiohttp import web

from .hypercolor_daemon import FakeHypercolorDaemon


@pytest.fixture
async def fake_daemon(
    unused_tcp_port_factory: Callable[[], int],
    socket_enabled: None,
) -> AsyncIterator[FakeHypercolorDaemon]:
    daemon = FakeHypercolorDaemon()
    app = web.Application()
    app.router.add_get("/api/v1/ws", daemon.websocket)
    app.router.add_post(
        "/api/v1/effects/{effect_id}/presets/{preset_id}/apply",
        daemon.apply_effect_preset,
    )
    app.router.add_post("/api/v1/effects/{effect_id}/apply", daemon.apply_effect)
    app.router.add_patch("/api/v1/effects/current/controls", daemon.update_controls)
    app.router.add_put("/api/v1/settings/brightness", daemon.set_brightness)
    app.router.add_put("/api/v1/output/power", daemon.set_output_power)
    app.router.add_put("/api/v1/devices/{device_id}", daemon.update_device)
    app.router.add_post("/api/v1/effects/stop", daemon.stop_effect)
    app.router.add_patch("/api/v1/scenes/{scene_id}/zones/{zone_id}", daemon.update_zone)
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
