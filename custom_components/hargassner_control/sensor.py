"""
Sensor entities for the Hargassner Control integration.

IMPORTANT: This integration is CONTROL ONLY.
Live boiler telemetry (temperatures, O2, pumps, buffer) is provided by the
BauerGroup IP-HargassnerIntegration (https://github.com/bauer-group/IP-HargassnerIntegration).

Only two sensor entities are exposed here:
  - last_sync    Timestamp of the last successful coordinator poll
  - connection   Online / Offline connectivity status
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HargassnerCoordinator
from .const import DOMAIN
from .number import _device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hargassner Control sensor entities."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        HargassnerLastSyncSensor(coordinator),
        HargassnerConnectionSensor(coordinator),
    ])


class HargassnerLastSyncSensor(CoordinatorEntity[HargassnerCoordinator], SensorEntity):
    """Timestamp of the last successful coordinator poll."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_sync"
    _attr_name = "Last Sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_state_class = None

    def __init__(self, coordinator: HargassnerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_last_sync"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> datetime | None:
        """Return UTC datetime of the last successful poll."""
        if self.coordinator.last_update_success and self.coordinator.data is not None:
            return datetime.now(tz=timezone.utc)
        return None


class HargassnerConnectionSensor(CoordinatorEntity[HargassnerCoordinator], SensorEntity):
    """Online / Offline connectivity status."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_name = "Connection Status"
    _attr_device_class = None
    _attr_state_class = None

    def __init__(self, coordinator: HargassnerCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_connection"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str:
        """Return 'online' or 'offline' based on last coordinator update."""
        return "online" if self.coordinator.last_update_success else "offline"

    @property
    def icon(self) -> str:
        return "mdi:lan-connect" if self.coordinator.last_update_success else "mdi:lan-disconnect"
