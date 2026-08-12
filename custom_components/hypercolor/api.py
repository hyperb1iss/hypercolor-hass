from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Never

import httpx

from hypercolor import (
    HypercolorApiError,
    HypercolorAuthenticationError,
    HypercolorClient,
    HypercolorError,
    HypercolorNotFoundError,
)


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

    client = HypercolorClient(
        host=host,
        port=port,
        api_key=api_key,
        httpx_client=httpx_client,
    )
    try:
        await client.get_output_power()
    except (HypercolorError, httpx.HTTPError, TypeError, ValueError) as exc:
        _raise_client_validation_error(exc, unsupported_not_found=True)

    if server_info.auth_required:
        try:
            await client.run_diagnostics(checks=[])
        except (HypercolorError, httpx.HTTPError, TypeError, ValueError) as exc:
            _raise_client_validation_error(exc)

    return server_info


def _raise_client_validation_error(
    error: Exception,
    *,
    unsupported_not_found: bool = False,
) -> Never:
    if isinstance(error, HypercolorAuthenticationError) or (
        isinstance(error, HypercolorApiError) and error.status_code == httpx.codes.FORBIDDEN
    ):
        raise InvalidAuthError from error
    if unsupported_not_found and isinstance(error, HypercolorNotFoundError):
        raise UnsupportedDaemonError from error
    raise CannotConnectError from error


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
