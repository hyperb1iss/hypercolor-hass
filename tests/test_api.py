from __future__ import annotations

import httpx
import pytest

from custom_components.hypercolor.api import (
    CannotConnectError,
    _normalize_server_info,
    async_validate_daemon,
)


def test_normalize_server_info_accepts_flat_generated_shape() -> None:
    server = _normalize_server_info(
        {
            "instance_id": "srv_1",
            "instance_name": "Hyperia",
            "version": "0.1.0",
            "auth_required": True,
            "device_count": 3,
        }
    )

    assert server.instance_id == "srv_1"
    assert server.instance_name == "Hyperia"
    assert server.auth_required is True
    assert server.device_count == 3


def test_normalize_server_info_accepts_daemon_identity_shape() -> None:
    server = _normalize_server_info(
        {
            "identity": {
                "instance_id": "srv_1",
                "instance_name": "Hyperia",
                "version": "0.1.0",
            },
            "auth_required": False,
            "device_count": 2,
        }
    )

    assert server.instance_id == "srv_1"
    assert server.instance_name == "Hyperia"
    assert server.version == "0.1.0"
    assert server.auth_required is False


async def test_validate_daemon_rejects_malformed_payload() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": {}}))
    ) as client:
        with pytest.raises(CannotConnectError):
            await async_validate_daemon(
                client,
                host="127.0.0.1",
                port=9420,
                api_key=None,
            )
