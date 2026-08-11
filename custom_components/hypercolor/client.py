from __future__ import annotations

from collections.abc import Awaitable
from inspect import signature
from typing import Any, Protocol

import httpx

from hypercolor import HypercolorClient, HypercolorNotFoundError

_NO_ACTIVE_EFFECT = "No effect is currently active"


class _EffectStopper(Protocol):
    def stop_effect(self) -> Awaitable[Any]: ...


def create_hypercolor_client(
    *,
    host: str,
    port: int,
    api_key: str | None,
    httpx_client: httpx.AsyncClient,
) -> HypercolorClient:
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "api_key": api_key,
    }
    if "httpx_client" in signature(HypercolorClient).parameters:
        kwargs["httpx_client"] = httpx_client
    return HypercolorClient(**kwargs)


async def async_stop_effect(client: _EffectStopper) -> None:
    try:
        await client.stop_effect()
    except HypercolorNotFoundError as exc:
        if str(exc) != _NO_ACTIVE_EFFECT:
            raise
