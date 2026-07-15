"""
DataUpdateCoordinator for the Hargassner Connect integration.

A single GET /widgets call every 15 minutes keeps all entities current.
All entities share this one coordinator — no per-entity polling.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_client import (
    HargassnerApiClient,
    HargassnerAuthError,
    HargassnerConnectionError,
    HargassnerData,
    HargassnerError,
)
from .const import DOMAIN, SCAN_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)


class HargassnerCoordinator(DataUpdateCoordinator[HargassnerData]):
    """Polls GET /widgets on a fixed schedule and shares the parsed result."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, client: HargassnerApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.client = client

    async def _async_update_data(self) -> HargassnerData:
        """Fetch fresh data; raise UpdateFailed so entities go unavailable on error."""
        try:
            data = await self.client.async_get_data()
        except HargassnerAuthError as exc:
            raise UpdateFailed(
                f"Authentication error — check your Hargassner Connect credentials: {exc}"
            ) from exc
        except HargassnerConnectionError as exc:
            raise UpdateFailed(f"Cannot reach the Hargassner Connect portal: {exc}") from exc
        except HargassnerError as exc:
            raise UpdateFailed(f"Hargassner API error: {exc}") from exc

        _LOGGER.debug(
            "Poll OK — %d widget(s), online=%s, pellets=%s kg",
            len(data.widgets),
            data.online,
            data.value("HEATER", "fuel_stock"),
        )
        return data
