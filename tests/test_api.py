from __future__ import annotations

import httpx
import pytest

from custom_components.hypercolor.api import (
    CannotConnectError,
    InvalidAuthError,
    UnsupportedDaemonError,
    _normalize_server_info,
    async_validate_daemon,
    url_host,
)
from tests.support import hypercolor_payloads as payloads


def test_normalize_server_info_reads_the_system_identity_block() -> None:
    server = _normalize_server_info(
        {
            "identity": {
                "instance_id": "srv_1",
                "instance_name": "Hyperia",
                "version": "0.4.0",
                "auth_required": True,
                "device_count": 3,
            },
            "status": None,
        }
    )

    assert server.instance_id == "srv_1"
    assert server.instance_name == "Hyperia"
    assert server.version == "0.4.0"
    assert server.auth_required is True
    assert server.device_count == 3


def test_normalize_server_info_rejects_a_flat_legacy_shape() -> None:
    with pytest.raises(KeyError):
        _normalize_server_info(
            {
                "instance_id": "srv_1",
                "instance_name": "Hyperia",
                "version": "0.3.2",
            }
        )


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


async def test_validate_daemon_rejects_read_only_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/system":
            return _envelope({"identity": _identity(auth_required=True), "status": None})
        return httpx.Response(403, json={"error": {"code": "forbidden"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(InvalidAuthError):
            await async_validate_daemon(
                client,
                host="127.0.0.1",
                port=9420,
                api_key="hc_ak_r_read_only",
            )


async def test_validate_daemon_uses_non_mutating_control_probe() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/v1/system":
            return _envelope({"identity": _identity(auth_required=True), "status": None})
        if request.url.path == "/api/v1/output":
            return _envelope({"power": "running", "brightness": 0.8})
        return _envelope(payloads.diagnostics())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        server = await async_validate_daemon(
            client,
            host="127.0.0.1",
            port=9420,
            api_key="hc_ak_control",
        )

    assert server.instance_id == "srv_1"
    assert requests == [
        ("GET", "/api/v1/system"),
        ("GET", "/api/v1/output"),
        ("POST", "/api/v1/diagnose"),
    ]


async def test_validate_daemon_rejects_missing_output_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/system":
            return _envelope({"identity": _identity(auth_required=True), "status": None})
        return httpx.Response(404, json={"error": {"code": "not_found"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsupportedDaemonError):
            await async_validate_daemon(
                client,
                host="127.0.0.1",
                port=9420,
                api_key="hc_ak_control",
            )


def _identity(*, auth_required: bool) -> dict[str, object]:
    identity = payloads.identity()
    identity.update({"instance_id": "srv_1", "auth_required": auth_required})
    return identity


def _envelope(data: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": data,
            "meta": {
                "api_version": "1.0",
                "request_id": "req_test",
                "timestamp": "2026-08-29T00:00:00Z",
            },
        },
    )


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("hyperia.local", "hyperia.local"),
        ("10.4.20.191", "10.4.20.191"),
        ("2601:600:8280:4bb1:561f:6d17:5c7c:14b7", "[2601:600:8280:4bb1:561f:6d17:5c7c:14b7]"),
        ("::1", "[::1]"),
    ],
)
def test_url_host_brackets_only_ipv6_literals(host: str, expected: str) -> None:
    assert url_host(host) == expected


async def test_validate_daemon_reaches_an_ipv6_daemon() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path == "/api/v1/system":
            return _envelope({"identity": _identity(auth_required=False), "status": None})
        return _envelope({"power": "running", "brightness": 0.8})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        server = await async_validate_daemon(
            client,
            host="2601:600:8280:4bb1:561f:6d17:5c7c:14b7",
            port=9420,
            api_key=None,
        )

    assert server.instance_id == "srv_1"
    assert [(url.host, url.port, url.path) for url in seen] == [
        ("2601:600:8280:4bb1:561f:6d17:5c7c:14b7", 9420, "/api/v1/system"),
        ("2601:600:8280:4bb1:561f:6d17:5c7c:14b7", 9420, "/api/v1/output"),
    ]


async def test_validate_daemon_reports_unparseable_hosts_as_cannot_connect() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": {}}))
    ) as client:
        with pytest.raises(CannotConnectError):
            await async_validate_daemon(
                client,
                host="hyperia:with:colons",
                port=9420,
                api_key=None,
            )
