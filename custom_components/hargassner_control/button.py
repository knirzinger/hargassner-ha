"""
Button entities for the Hargassner Connect integration.

- force_charge     : immediate hot-water charge (Warmwasser sofort laden)
- confirm_events   : acknowledge all pending events/warnings (NEW in 0.1.2)

Buttons are created only when the underlying widget/action is present.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WIDGET_BOILER, WIDGET_EVENTS
from .coordinator import HargassnerCoordinator
from .number import _device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Create button entities based on what the payload supports."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if data is None:
        return

    entities: list[ButtonEntity] = []

    # Force hot-water charge — construct the action resource from the boiler widget.
    boiler = data.widget(WIDGET_BOILER)
    if boiler is not None:
        number = boiler.number or "1"
        resource = (
            f"/installations/{coordinator.client.installation_id}"
            f"/widgets/boilers/{number}/actions/force-charging"
        )
        entities.append(
            HargassnerButtonEntity(
                coordinator,
                ButtonEntityDescription(
                    key="force_charge",
                    translation_key="force_charge",
                    device_class=ButtonDeviceClass.RESTART,
                    icon="mdi:water-boiler",
                ),
                resource,
            )
        )

    # Acknowledge all events — only if the events widget exposes the action.
    confirm_resource = data.action(WIDGET_EVENTS, "confirm_all")
    if confirm_resource:
        entities.append(
            HargassnerButtonEntity(
                coordinator,
                ButtonEntityDescription(
                    key="confirm_events",
                    translation_key="confirm_events",
                    icon="mdi:check-all",
                ),
                confirm_resource,
            )
        )

    async_add_entities(entities)


class HargassnerButtonEntity(CoordinatorEntity[HargassnerCoordinator], ButtonEntity):
    """A one-shot action button for the Hargassner boiler."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HargassnerCoordinator,
        description: ButtonEntityDescription,
        resource: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._resource = resource
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        if not self._resource:
            raise HomeAssistantError(f"{self.entity_id}: no action resource available.")
        await self.coordinator.client.async_post_action(self._resource)
        await self.coordinator.async_request_refresh()
