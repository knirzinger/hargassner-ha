"""
Select entities for the Hargassner Connect integration.

Options are taken from the live API (so all modes a device supports appear
automatically, e.g. the one-time bridge heating/reduction modes). Option strings
are lowercased for HA/translation keys and upper-cased again on write to match
the API (MODE_AUTOMATIC, PROGRAM_BOILER, ...).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    WIDGET_BUFFER,
    WIDGET_HEATER,
    WIDGET_HEATING_CIRCUIT,
)
from .coordinator import HargassnerCoordinator
from .number import _device_info

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class HargassnerSelectDescription(SelectEntityDescription):
    """Select description bound to a widget parameter."""

    widget_prefix: str
    param_key: str


SELECT_DESCRIPTIONS: tuple[HargassnerSelectDescription, ...] = (
    HargassnerSelectDescription(
        key="heating_mode",
        translation_key="heating_mode",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="mode",
    ),
    HargassnerSelectDescription(
        key="solar_mode",
        translation_key="solar_mode",
        widget_prefix=WIDGET_BUFFER,
        param_key="solar_mode_active",
    ),
    # NEW in 0.1.2 — heater operating program
    HargassnerSelectDescription(
        key="heater_program",
        translation_key="heater_program",
        widget_prefix=WIDGET_HEATER,
        param_key="program",
        icon="mdi:fire",
    ),
    # Only appears on devices that expose it (absent on Classic)
    HargassnerSelectDescription(
        key="bathroom_heating",
        translation_key="bathroom_heating",
        widget_prefix=WIDGET_HEATING_CIRCUIT,
        param_key="bathroom_heating",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Create select entities for enum parameters present in the payload."""
    coordinator: HargassnerCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if data is None:
        return
    entities = []
    for desc in SELECT_DESCRIPTIONS:
        param = data.param(desc.widget_prefix, desc.param_key)
        if param is not None and param.options:
            entities.append(HargassnerSelectEntity(coordinator, desc))
    async_add_entities(entities)


class HargassnerSelectEntity(CoordinatorEntity[HargassnerCoordinator], SelectEntity):
    """A controllable enum parameter on the Hargassner boiler."""

    _attr_has_entity_name = True
    entity_description: HargassnerSelectDescription

    def __init__(
        self, coordinator: HargassnerCoordinator, description: HargassnerSelectDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)
        param = self._param
        api_options = param.options if param and param.options else []
        self._attr_options = [str(o).lower() for o in api_options]

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
    def current_option(self) -> str | None:
        param = self._param
        if not param or param.value is None:
            return None
        value = str(param.value).lower()
        if value not in self._attr_options:
            _LOGGER.warning(
                "%s: unexpected value %r from API (known options: %s)",
                self.entity_id, value, self._attr_options,
            )
            return None
        return value

    async def async_select_option(self, option: str) -> None:
        param = self._param
        if not param or not param.resource:
            raise HomeAssistantError(
                f"{self.entity_id}: parameter is not currently writable."
            )
        await self.coordinator.client.async_patch_resource(param.resource, option.upper())
        await self.coordinator.async_request_refresh()
