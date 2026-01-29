from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .appliance_controls import WriteBooleanControl, generate_controls_from_config
from .config_flow import EntryData
from .const import DOMAIN
from .entity import HomeWhizEntity
from .helper import build_entry_data
from .homewhiz import HomewhizCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


class HomeWhizSwitchEntity(HomeWhizEntity, SwitchEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        control: WriteBooleanControl,
        device_name: str,
        data: EntryData,
    ):
        super().__init__(coordinator, device_name, control.key, data)
        self._control = control

    @property
    def is_on(self) -> bool | None:  # type: ignore[override]
        if self.coordinator.data is None:
            return None
        return self._control.get_value(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.send_command(self._control.set_value(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.send_command(self._control.set_value(False))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up HomeWhiz switch entities."""
    data = build_entry_data(entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # CRITICAL FIX (Issue #295): Skip switch entities for read-only devices
    if entry.data.get("config_missing") is True:
        _LOGGER.debug(
            "Skipping switch entities for read-only device '%s' (config_missing=True)",
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

    write_enum_controls = [c for c in controls if isinstance(c, WriteBooleanControl)]

    _LOGGER.debug("Switches: %s", [c.key for c in write_enum_controls])

    async_add_entities(
        [
            HomeWhizSwitchEntity(coordinator, control, entry.title, data)
            for control in write_enum_controls
        ]
    )
