"""
Select entities for the Hargassner Connect integration.

Each SelectEntity maps to one writable enum parameter on the boiler.
Reads come from the shared coordinator (WidgetSnapshot).
Writes go directly to the API then trigger a coordinator refresh.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HargassnerCoordinator
from .api_client import BathroomHeating, HeatingMode, SolarMode, WidgetSnapshot
from .const import DOMAIN
from .number import _device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HargassnerSelectDescription(SelectEntityDescription):
    """Extends SelectEntityDescription with Hargassner-specific fields."""

    options: list[str]
    value_fn: Callable[[WidgetSnapshot], str | None]
    set_option_fn: Callable[[Any, str], Any]


SELECT_DESCRIPTIONS: tuple[HargassnerSelectDescription, ...] = (
    HargassnerSelectDescription(
        key="heating_mode",
        translation_key="heating_mode",
        name="Heating Mode",
        options=[m.value for m in HeatingMode],
        value_fn=lambda s: s.heating_circuit.mode,
        set_option_fn=lambda client, v: client.async_set_heating_mode(v),
    ),
    HargassnerSelectDescription(
        key="solar_mode",
        translation_key="solar_mode",
        name="Solar Mode",
        options=[m.value for m in SolarMode],
        value_fn=lambda s: s.buffer.solar_mode_active,
        set_option_fn=lambda client, v: client.async_set_solar_mode(v),
    ),
    HargassnerSelectDescription(
        key="bathroom_heating",
        translation_key="bathroom_heating",
        name="Bathroom Heating (Badewanne)",
        options=[m.value for m in BathroomHeating],
        value_fn=lambda s: s.heating_circuit.bathroom_heating,
        set_option_fn=lambda client, v: client.async_set_bathroom_heating(v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hargassner select entities from a config entry."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HargassnerSelectEntity(coordinator, description)
        for description in SELECT_DESCRIPTIONS
    )


class HargassnerSelectEntity(CoordinatorEntity[HargassnerCoordinator], SelectEntity):
    """A controllable enum parameter on the Hargassner boiler."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HargassnerCoordinator,
        description: HargassnerSelectDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_options = description.options
        self._attr_device_info = _device_info(coordinator)

    @property
    def current_option(self) -> str | None:
        """Return the current option from the coordinator snapshot."""
        if self.coordinator.data is None:
            return None
        value = self.entity_description.value_fn(self.coordinator.data)
        if value not in self._attr_options:
            _LOGGER.warning(
                "%s: unexpected value %r from API (known options: %s)",
                self.entity_id, value, self._attr_options,
            )
            return None
        return value

    async def async_select_option(self, option: str) -> None:
        """Send the selected option to the boiler and refresh state."""
        await self.entity_description.set_option_fn(self.coordinator.client, option)
        await self.coordinator.async_request_refresh()
