from __future__ import annotations

import pytest

from custom_components.hypercolor.client import async_stop_effect
from hypercolor import HypercolorNotFoundError


class _StopClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.stop_calls = 0

    async def stop_effect(self) -> None:
        self.stop_calls += 1
        if self.error is not None:
            raise self.error


async def test_stop_effect_succeeds_normally() -> None:
    client = _StopClient()

    await async_stop_effect(client)

    assert client.stop_calls == 1


async def test_stop_effect_accepts_already_stopped_response() -> None:
    client = _StopClient(HypercolorNotFoundError("No effect is currently active"))

    await async_stop_effect(client)

    assert client.stop_calls == 1


async def test_stop_effect_preserves_other_not_found_errors() -> None:
    client = _StopClient(HypercolorNotFoundError("Stop endpoint is unavailable"))

    with pytest.raises(HypercolorNotFoundError, match="Stop endpoint is unavailable"):
        await async_stop_effect(client)
