"""
Number entities for the Hargassner Connect integration.

Entities are created dynamically: a control is only added when the matching
writable parameter is actually present in the live /widgets payload. Range and
step come from the API itself. Writes go to the parameter's own ``resource`` URL.
This makes the integration adapt automatically to different boiler models.
"""
from __future__ import annotations

import logging
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    WIDGET_BOILER,
    WIDGET_HEATER,
    WIDGET_HEATING_CIRCUIT,
)
from .coordinator import HargassnerCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HargassnerNumberDescription(NumberEntityDescription):
    """Number description bound to a widget parameter."""

    widget_prefix: str
    param_key: str
    default_min: float = 0.0
    default_max: float = 100.0
    default_step: float = 1.0


NUMBER_DESCRIPTIONS: tuple[HargassnerNumberDescription, ...] = (
    # --- Domestic hot water (NEW in 0.1.2) ---
    HargassnerNumberDescription(
        key="hot_water_temperature",
        translation_key="hot_water_temperature",
        widget_prefix=WIDGET_BOILER,
        param_key="boiler_temperature_target",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=10.0, default_max=84.0, default_step=1.0,
        mode=NumberMode.BOX,
    ),
    # --- Pellet stock (moved to HEATER widget, real max used) ---
    HargassnerNumberDescription(
        key="pellet_stock",
        translation_key="pellet_stock",
        widget_prefix=WIDGET_HEATER,
        param_key="fuel_stock",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        default_min=0.0, default_max=7874.0, default_step=1.0,
        mode=NumberMode.BOX,
        icon="mdi:sack",
    ),
    # --- Heating circuit: everyday correction (±3) ---
    HargassnerNumberDescription(
        key="room_temperature_correction",
        translation_key="room_temperature_correction",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="room_temperature_correction",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=-3.0, default_max=3.0, default_step=0.5,
        mode=NumberMode.BOX,
    ),
    # --- Advanced heating-circuit setpoints (only appear on devices that expose
    #     them, e.g. Nano.2; absent on Classic — created dynamically) ---
    HargassnerNumberDescription(
        key="room_temperature_heating",
        translation_key="room_temperature_heating",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="room_temperature_heating",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=10.0, default_max=30.0, default_step=0.5,
        mode=NumberMode.BOX,
    ),
    HargassnerNumberDescription(
        key="room_temperature_reduction",
        translation_key="room_temperature_reduction",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="room_temperature_reduction",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=10.0, default_max=30.0, default_step=0.5,
        mode=NumberMode.BOX,
    ),
    HargassnerNumberDescription(
        key="steepness",
        translation_key="steepness",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="steepness",
        native_unit_of_measurement=None,
        default_min=0.2, default_max=3.5, default_step=0.05,
        mode=NumberMode.SLIDER,
        icon="mdi:slope-uphill",
    ),
    HargassnerNumberDescription(
        key="deactivation_limit_heating",
        translation_key="deactivation_limit_heating",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="deactivation_limit_heating",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=-10.0, default_max=50.0, default_step=1.0,
        mode=NumberMode.BOX,
    ),
    HargassnerNumberDescription(
        key="deactivation_limit_reduction_day",
        translation_key="deactivation_limit_reduction_day",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="deactivation_limit_reduction_day",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=-40.0, default_max=50.0, default_step=1.0,
        mode=NumberMode.BOX,
    ),
    HargassnerNumberDescription(
        key="deactivation_limit_reduction_night",
        translation_key="deactivation_limit_reduction_night",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="deactivation_limit_reduction_night",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        default_min=-40.0, default_max=50.0, default_step=1.0,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Create number entities for parameters present in the payload."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if data is None:
        return
    entities = [
        HargassnerNumberEntity(coordinator, desc)
        for desc in NUMBER_DESCRIPTIONS
        if data.param(desc.widget_prefix, desc.param_key) is not None
    ]
    async_add_entities(entities)


class HargassnerNumberEntity(CoordinatorEntity[HargassnerCoordinator], NumberEntity):
    """A controllable numeric parameter on the Hargassner boiler."""

    _attr_has_entity_name = True
    entity_description: HargassnerNumberDescription

    def __init__(
        self, coordinator: HargassnerCoordinator, description: HargassnerNumberDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

        param = self._param
        self._attr_native_min_value = (
            float(param.minimum) if param and param.minimum is not None
            else description.default_min
        )
        self._attr_native_max_value = (
            float(param.maximum) if param and param.maximum is not None
            else description.default_max
        )
        self._attr_native_step = (
            float(param.step) if param and param.step is not None
            else description.default_step
        )

    @property
    def _param(self):
        data = self.coordinator.data
        if data is None:
            return None
        return data.param(self.entity_description.widget_prefix, self.entity_description.param_key)

    @property
    def available(self) -> bool:
        return super().available and self._param is not None

    @property
    def native_value(self) -> float | None:
        param = self._param
        if param and param.value is not None:
            try:
                return float(param.value)
            except (TypeError, ValueError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        param = self._param
        if not param or not param.resource:
            raise HomeAssistantError(
                f"{self.entity_id}: parameter is not currently writable."
            )
        await self.coordinator.client.async_patch_resource(param.resource, value)
        await self.coordinator.async_request_refresh()


def _device_info(coordinator: HargassnerCoordinator) -> DeviceInfo:
    """Device registry info shared by all Hargassner entities."""
    data = coordinator.data
    name = data.device_name if data else "Hargassner"
    model = data.device_model if data else "Pellematic"
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
        name=name,
        manufacturer="Hargassner",
        model=model,
        configuration_url="https://web.hargassner.at",
    )
