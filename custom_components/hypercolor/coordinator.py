from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from hypercolor import HypercolorAuthenticationError

from .const import DOMAIN
from .runtime_data import ConnectionState

_LOGGER = logging.getLogger(__name__)


class HypercolorCoordinator(DataUpdateCoordinator[Any]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        config_entry: ConfigEntry[Any],
        name: str,
        loader: Callable[[], Awaitable[Any]],
        connection_state: ConnectionState,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}.{name}",
            update_interval=None,
            config_entry=config_entry,
        )
        self._loader = loader
        self._connection_state = connection_state

    async def _async_update_data(self) -> Any:
        try:
            data = await self._loader()
        except HypercolorAuthenticationError as exc:
            self._connection_state.set_disconnected(exc)
            raise ConfigEntryAuthFailed from exc
        except Exception as exc:
            self._connection_state.set_disconnected(exc)
            raise
        self._connection_state.set_connected()
        return data


async def reconcile_loop(
    coordinators: list[HypercolorCoordinator],
    interval_s: int,
) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await asyncio.gather(
            *(coordinator.async_request_refresh() for coordinator in coordinators)
        )
