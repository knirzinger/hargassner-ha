"""
Button entities for the Hargassner Connect integration.

ButtonEntity triggers a one-shot action on the boiler with no state to read back.
Currently: Force Charge (immediate hot-water boost / Badewanne action).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HargassnerCoordinator
from .const import DOMAIN
from .number import _device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HargassnerButtonDescription(ButtonEntityDescription):
    """Extends ButtonEntityDescription with the action coroutine factory."""
    press_fn: Callable[[Any], Any]   # (client) -> coroutine


BUTTON_DESCRIPTIONS: tuple[HargassnerButtonDescription, ...] = (
    HargassnerButtonDescription(
        key="force_charge",
        translation_key="force_charge",
        name="Force Charge",
        device_class=ButtonDeviceClass.RESTART,
        press_fn=lambda client: client.async_force_charge(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hargassner button entities from a config entry."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HargassnerButtonEntity(coordinator, description)
        for description in BUTTON_DESCRIPTIONS
    )


class HargassnerButtonEntity(CoordinatorEntity[HargassnerCoordinator], ButtonEntity):
    """
    A one-shot action button for the Hargassner boiler.

    Pressing fires the action immediately.  A coordinator refresh follows so
    any state changes caused by the action are reflected in HA promptly.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HargassnerCoordinator,
        description: HargassnerButtonDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        """Fire the action then refresh coordinator state."""
        await self.entity_description.press_fn(self.coordinator.client)
        await self.coordinator.async_request_refresh()
