from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .const import CONF_API_KEY


class CannotConnectError(Exception):
    pass


class InvalidAuthError(Exception):
    pass


class UnsupportedDaemonError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ServerInfo:
    instance_id: str
    instance_name: str
    version: str
    auth_required: bool
    device_count: int


async def async_validate_daemon(
    httpx_client: httpx.AsyncClient,
    *,
    host: str,
    port: int,
    api_key: str | None,
) -> ServerInfo:
    root_url = f"http://{host}:{port}"
    try:
        server_response = await httpx_client.get(f"{root_url}/api/v1/server")
    except httpx.HTTPError as exc:
        raise CannotConnectError from exc

    if server_response.status_code == httpx.codes.UNAUTHORIZED:
        raise InvalidAuthError
    if server_response.status_code >= httpx.codes.BAD_REQUEST:
        raise CannotConnectError

    try:
        server_info = _normalize_server_info(_server_payload(server_response.json()))
    except (KeyError, TypeError, ValueError) as exc:
        raise CannotConnectError from exc

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        output_probe = await httpx_client.get(
            f"{root_url}/api/v1/output/power",
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise CannotConnectError from exc
    if output_probe.status_code in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
        raise InvalidAuthError
    if output_probe.status_code == httpx.codes.NOT_FOUND:
        raise UnsupportedDaemonError
    if output_probe.status_code >= httpx.codes.BAD_REQUEST:
        raise CannotConnectError

    if server_info.auth_required:
        try:
            control_probe = await httpx_client.post(
                f"{root_url}/api/v1/diagnose",
                headers=headers,
                json={"checks": []},
            )
        except httpx.HTTPError as exc:
            raise CannotConnectError from exc

        if control_probe.status_code in {
            httpx.codes.UNAUTHORIZED,
            httpx.codes.FORBIDDEN,
        }:
            raise InvalidAuthError
        if control_probe.status_code >= httpx.codes.BAD_REQUEST:
            raise CannotConnectError

    return server_info


def auth_headers(entry_data: dict[str, Any]) -> dict[str, str]:
    api_key = entry_data.get(CONF_API_KEY)
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _server_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise TypeError
    return data


def _normalize_server_info(data: dict[str, Any]) -> ServerInfo:
    identity = data.get("identity")
    if isinstance(identity, dict):
        instance_id = str(identity["instance_id"])
        instance_name = str(identity["instance_name"])
        version = str(identity["version"])
    else:
        instance_id = str(data["instance_id"])
        instance_name = str(data["instance_name"])
        version = str(data["version"])

    return ServerInfo(
        instance_id=instance_id,
        instance_name=instance_name,
        version=version,
        auth_required=bool(data.get("auth_required", False)),
        device_count=int(data.get("device_count", 0)),
    )
