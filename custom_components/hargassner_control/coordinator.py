"""
DataUpdateCoordinator for the Hargassner Connect integration.

Single GET /widgets call every 15 minutes keeps all entities current.
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
    HargassnerError,
    WidgetSnapshot,
)
from .const import DOMAIN, SCAN_INTERVAL_MINUTES

_LOGGER = logging.getLogger(__name__)


class HargassnerCoordinator(DataUpdateCoordinator[WidgetSnapshot]):
    """
    Coordinator that polls GET /widgets on a fixed schedule.

    All sensor, number, select, button, and binary_sensor entities subscribe
    to this coordinator and read from ``coordinator.data`` (a WidgetSnapshot).
    Write operations (PATCH / POST) call the api_client directly and then
    call ``async_request_refresh()`` to sync state back promptly.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: HargassnerApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.client = client

    async def _async_update_data(self) -> WidgetSnapshot:
        """
        Fetch a fresh WidgetSnapshot from the API.

        Called automatically by the coordinator on the poll interval, and
        manually via ``async_request_refresh()`` after any write operation.

        Raises ``UpdateFailed`` on any error so HA marks entities unavailable
        rather than showing stale data silently.
        """
        try:
            snapshot = await self.client.async_get_widgets()
        except HargassnerAuthError as exc:
            raise UpdateFailed(
                f"Authentication error — check your Hargassner Connect credentials: {exc}"
            ) from exc
        except HargassnerConnectionError as exc:
            raise UpdateFailed(
                f"Cannot reach the Hargassner Connect portal: {exc}"
            ) from exc
        except HargassnerError as exc:
            raise UpdateFailed(f"Hargassner API error: {exc}") from exc

        _LOGGER.debug(
            "Poll OK — boiler %s°C, mode %s, pellets %s kg",
            snapshot.boiler.temperature,
            snapshot.heating_circuit.mode,
            snapshot.pellet_stock_kg,
        )
        return snapshot
