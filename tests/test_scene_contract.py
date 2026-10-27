from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from custom_components.hypercolor.api import ServerInfo
from custom_components.hypercolor.coordinator import HypercolorCoordinator
from custom_components.hypercolor.models import primary_effect_layer
from custom_components.hypercolor.runtime_data import HypercolorRuntimeData
from hypercolor import (
    HypercolorClient,
    HypercolorConnectionError,
    HypercolorPreconditionError,
    scene_fence,
)
from tests.support import hypercolor_payloads as payloads


async def test_scene_snapshot_preserves_daemon_epoch_and_effect_identity() -> None:
    document = payloads.scene_document([payloads.zone("rainbow", {}, None)], revision=12)
    document["run_epoch"] = "daemon-run-a"
    response = httpx.Response(
        200,
        headers={"ETag": '"daemon-run-a:12"', "Hypercolor-Run-Epoch": "daemon-run-a"},
        json={
            "data": document,
            "meta": {"api_version": "1.0", "request_id": "read", "timestamp": "2026-10-27"},
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as http:
        client = HypercolorClient(httpx_client=http)
        scene = await client.get_live_scene()

    assert scene.run_epoch == "daemon-run-a"
    assert scene_fence(scene) == '"daemon-run-a:12"'
    layer = primary_effect_layer(scene)
    assert layer is not None
    assert layer.effect_id == "rainbow"


async def test_scene_precondition_failure_refreshes_without_replaying_the_write() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            412,
            headers={"ETag": '"daemon-run-b:12"', "Hypercolor-Run-Epoch": "daemon-run-b"},
            json={
                "error": {
                    "code": "precondition_failed",
                    "message": "Scene changed",
                    "details": {"current": 12},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        runtime, refresh = _runtime(HypercolorClient(httpx_client=http))
        with pytest.raises(HypercolorPreconditionError) as caught:
            await runtime.async_mutate(
                lambda: runtime.client.update_zone(
                    payloads.PRIMARY_ZONE_ID, enabled=False, if_match='"daemon-run-a:12"'
                )
            )

    assert caught.value.current_revision == 12
    assert caught.value.current_fence == '"daemon-run-b:12"'
    assert len(requests) == 1
    assert requests[0].headers["If-Match"] == '"daemon-run-a:12"'
    refresh.assert_awaited_once()


async def test_unanswered_scene_write_refreshes_without_replaying_the_write() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("response lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        runtime, refresh = _runtime(HypercolorClient(httpx_client=http))
        with pytest.raises(HypercolorConnectionError):
            await runtime.async_stop_effect()

    assert len(requests) == 1
    assert requests[0].url.path == "/api/v1/scene/clear"
    refresh.assert_awaited_once()


def _runtime(client: HypercolorClient) -> tuple[HypercolorRuntimeData, AsyncMock]:
    coordinator = MagicMock(spec=HypercolorCoordinator)
    refresh = AsyncMock()
    coordinator.async_refresh = refresh
    runtime = HypercolorRuntimeData(
        client=client,
        coordinator=coordinator,
        server=ServerInfo(
            instance_id="srv-contract",
            instance_name="Contract",
            version="0.8.0",
            auth_required=False,
            device_count=0,
        ),
    )
    return runtime, refresh
