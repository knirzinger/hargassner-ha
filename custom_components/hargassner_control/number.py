"""
Number entities for the Hargassner Connect integration.

Each NumberEntity maps to one writable float parameter on the boiler.
Reads come from the shared coordinator (WidgetSnapshot).
Writes go directly to the API then trigger a coordinator refresh.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfMass, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HargassnerCoordinator
from .api_client import WidgetSnapshot
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HargassnerNumberDescription(NumberEntityDescription):
    """Extends NumberEntityDescription with Hargassner-specific fields."""

    value_fn: Callable[[WidgetSnapshot], float | None]
    set_value_fn: Callable[[Any, float], Any]  # (client, value) -> coroutine


NUMBER_DESCRIPTIONS: tuple[HargassnerNumberDescription, ...] = (
    HargassnerNumberDescription(
        key="room_temperature_correction",
        translation_key="room_temperature_correction",
        name="Room Temperature Correction",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=-3.0,
        native_max_value=3.0,
        native_step=0.5,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.room_temp_correction,
        set_value_fn=lambda client, v: client.async_set_room_temp_correction(v),
    ),
    HargassnerNumberDescription(
        key="room_temperature_heating",
        translation_key="room_temperature_heating",
        name="Room Temperature (Heating)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=10.0,
        native_max_value=30.0,
        native_step=0.5,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.room_temp_heating,
        set_value_fn=lambda client, v: client.async_set_room_temp_heating(v),
    ),
    HargassnerNumberDescription(
        key="room_temperature_reduction",
        translation_key="room_temperature_reduction",
        name="Room Temperature (Reduction)",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=10.0,
        native_max_value=30.0,
        native_step=0.5,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.room_temp_reduction,
        set_value_fn=lambda client, v: client.async_set_room_temp_reduction(v),
    ),
    HargassnerNumberDescription(
        key="steepness",
        translation_key="steepness",
        name="Heating Curve Steepness",
        native_unit_of_measurement=None,
        native_min_value=0.2,
        native_max_value=3.5,
        native_step=0.05,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.steepness,
        set_value_fn=lambda client, v: client.async_set_steepness(v),
    ),
    HargassnerNumberDescription(
        key="deactivation_limit_heating",
        translation_key="deactivation_limit_heating",
        name="Heating Off Temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=-10.0,
        native_max_value=30.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.deactivation_limit_heating,
        set_value_fn=lambda client, v: client.async_set_deactivation_limit_heating(v),
    ),
    HargassnerNumberDescription(
        key="deactivation_limit_reduction_day",
        translation_key="deactivation_limit_reduction_day",
        name="Day Setback Off Temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=-10.0,
        native_max_value=30.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.deactivation_limit_reduction_day,
        set_value_fn=lambda client, v: client.async_set_deactivation_limit_reduction_day(v),
    ),
    HargassnerNumberDescription(
        key="deactivation_limit_reduction_night",
        translation_key="deactivation_limit_reduction_night",
        name="Night Setback Off Temp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=-10.0,
        native_max_value=30.0,
        native_step=1.0,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.heating_circuit.deactivation_limit_reduction_night,
        set_value_fn=lambda client, v: client.async_set_deactivation_limit_reduction_night(v),
    ),
    HargassnerNumberDescription(
        key="pellet_stock",
        translation_key="pellet_stock",
        name="Pellet Stock",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        native_min_value=0.0,
        native_max_value=5000.0,
        native_step=10.0,
        mode=NumberMode.BOX,
        value_fn=lambda s: s.pellet_stock_kg,
        set_value_fn=lambda client, v: client.async_set_pellet_stock(v),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hargassner number entities from a config entry."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HargassnerNumberEntity(coordinator, description)
        for description in NUMBER_DESCRIPTIONS
    )


class HargassnerNumberEntity(CoordinatorEntity[HargassnerCoordinator], NumberEntity):
    """A controllable numeric parameter on the Hargassner boiler."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HargassnerCoordinator,
        description: HargassnerNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> float | None:
        """Return the current value from the coordinator snapshot."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the boiler and refresh state."""
        await self.entity_description.set_value_fn(self.coordinator.client, value)
        await self.coordinator.async_request_refresh()


def _device_info(coordinator: HargassnerCoordinator) -> dict:
    """Return the device registry info shared by all Hargassner entities."""
    from homeassistant.helpers.device_registry import DeviceInfo
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name="Hargassner Pellematic",
        manufacturer="Hargassner",
        model="Pellematic",
        configuration_url="https://web.hargassner.at",
    )
