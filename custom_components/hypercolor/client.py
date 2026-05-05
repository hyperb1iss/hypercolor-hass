from __future__ import annotations

from inspect import signature
from typing import Any

import httpx

from hypercolor import HypercolorClient


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
