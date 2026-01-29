from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .appliance_controls import (
    BooleanBitmaskControl,
    BooleanCompareControl,
    generate_controls_from_config,
)
from .config_flow import EntryData
from .const import DOMAIN
from .entity import HomeWhizEntity
from .helper import build_entry_data
from .homewhiz import HomewhizCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


class HomeWhizBinarySensorEntity(HomeWhizEntity, BinarySensorEntity):
    """Binary sensor entity for HomeWhiz appliances."""

    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        control: BooleanBitmaskControl | BooleanCompareControl,
        device_name: str,
        data: EntryData,
    ) -> None:
        super().__init__(coordinator, device_name, control.key, data)
        self._control = control

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self._control.get_value(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomeWhiz binary sensor entities."""
    data = build_entry_data(entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # CRITICAL FIX (Issue #295): Skip binary sensor entities for read-only devices
    if entry.data.get("config_missing") is True:
        _LOGGER.debug(
            "Skipping binary sensor entities for read-only device '%s' (config_missing=True)",
            entry.title,
        )
        return

    try:
        controls = generate_controls_from_config(entry.entry_id, data.contents.config)
    except Exception as err:
        _LOGGER.error(
            "Failed to generate controls for device '%s': %s",
            entry.title,
            err,
            exc_info=True,
        )
        return

    # Binary sensors are read-only boolean controls (BooleanBitmaskControl, BooleanCompareControl)
    binary_sensor_controls = [
        c
        for c in controls
        if isinstance(c, (BooleanBitmaskControl, BooleanCompareControl))
    ]

    _LOGGER.debug(
        "Binary sensor controls for '%s': %s",
        entry.title,
        [c.key for c in binary_sensor_controls],
    )

    homewhiz_binary_sensor_entities = [
        HomeWhizBinarySensorEntity(coordinator, control, entry.title, data)
        for control in binary_sensor_controls
    ]

    async_add_entities(homewhiz_binary_sensor_entities)
