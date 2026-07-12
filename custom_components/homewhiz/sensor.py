from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .appliance_controls import (
    DebugControl,
    EnumControl,
    NumericControl,
    StateAwareRemainingTimeControl,
    SummedTimestampControl,
    TimeControl,
    generate_controls_from_config,
)
from .config_flow import EntryData
from .const import DOMAIN
from .entity import HomeWhizEntity
from .helper import build_entry_data
from .homewhiz import HomewhizCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Function-based sensors for read-only devices (e.g. air quality sensor, Issue #295).
# key -> (label, unit, icon, device_class)
FUNCTION_SENSORS: dict[
    str, tuple[str, str | None, str | None, SensorDeviceClass | None]
] = {
    "STT_CO2": ("CO2", "ppm", "mdi:molecule-co2", SensorDeviceClass.CO2),
    "STT_HUMIDITY": ("Humidity", "%", "mdi:water-percent", None),
    "STT_TEMPERATURE": ("Temperature", "°C", "mdi:thermometer", None),
    # STT_RAW_* (device-internal, uncompensated sensor readings) are not shown
    # in the HomeWhiz app and confuse users → not exposed (Issue #394).
    "STT_CO2_LEVEL": ("CO2 Level", None, None, SensorDeviceClass.ENUM),
    "STT_HEALTH_STATUS": ("Health Status", None, None, SensorDeviceClass.ENUM),
    "ATR_BRIGHTNESS": ("Brightness", None, "mdi:brightness-6", None),
    "ATR_SLEEP_MODE": ("Sleep Mode", None, "mdi:sleep", None),
}


class HomeWhizSensorEntity(HomeWhizEntity, SensorEntity):
    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        control: TimeControl
        | EnumControl
        | NumericControl
        | DebugControl
        | SummedTimestampControl
        | StateAwareRemainingTimeControl,
        device_name: str,
        data: EntryData,
    ):
        super().__init__(coordinator, device_name, control.key, data)
        self._control = control
        if isinstance(control, (TimeControl, StateAwareRemainingTimeControl)):
            self._attr_icon = "mdi:clock-outline"
            self._attr_native_unit_of_measurement = "min"
            self._attr_device_class = SensorDeviceClass.DURATION
        elif isinstance(control, EnumControl):
            self._attr_device_class = SensorDeviceClass.ENUM  # type:ignore
            self._attr_options = list(self._control.options.values())  # type:ignore
        elif isinstance(control, SummedTimestampControl):
            self._attr_icon = "mdi:camera-timer"
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:  # type: ignore[override]
        """Attribute to identify the origin of the data used"""
        if isinstance(self._control, SummedTimestampControl):
            return {
                "sources": [
                    x.my_entity_ids
                    for x in self._control.sensors
                    if hasattr(x, "my_entity_ids")
                ]
            }
        return None

    @property
    def native_value(  # type: ignore[override]
        self,
    ) -> float | int | str | datetime | None:
        _LOGGER.debug(
            "Native value for entity %s, id: %s, info: %s, class:%s, is %s",
            self.entity_key,
            self._attr_unique_id,
            self._attr_device_info,
            self._attr_device_class,
            self.coordinator.data,
        )

        if self.coordinator.data is None:
            return None
        return self._control.get_value(self.coordinator.data)


class HomeWhizFunctionSensor(HomeWhizEntity, SensorEntity):
    """Sensor for read-only devices using a functions dict (Issue #295)."""

    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        device_name: str,
        data: EntryData,
        function_key: str,
        label: str,
        unit: str | None = None,
        icon: str | None = None,
        device_class: SensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator, device_name, function_key.lower(), data)
        self._function_key = function_key
        self._attr_name = label
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class

    @property
    def native_value(  # type: ignore[override]
        self,
    ) -> float | int | str | None:
        if isinstance(self.coordinator.data, dict):
            return self.coordinator.data.get(self._function_key)
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = build_entry_data(entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Read-only devices (e.g. air quality sensor, Issue #295) have no ProcAM
    # config; expose their reported functions as plain sensors instead.
    if entry.data.get("config_missing") is True:
        async_add_entities(
            HomeWhizFunctionSensor(
                coordinator,
                entry.title,
                data,
                func_key,
                label,
                unit=unit,
                icon=icon,
                device_class=device_class,
            )
            for func_key, (
                label,
                unit,
                icon,
                device_class,
            ) in FUNCTION_SENSORS.items()
        )
        return

    controls = generate_controls_from_config(entry.entry_id, data.contents.config)
    _LOGGER.debug("Generated controls: %s", controls)
    sensor_controls = [
        c
        for c in controls
        if isinstance(
            c,
            (
                TimeControl,
                EnumControl,
                NumericControl,
                DebugControl,
                SummedTimestampControl,
                StateAwareRemainingTimeControl,
            ),
        )
    ]

    _LOGGER.debug("Sensors: %s", [c.key for c in sensor_controls])

    homewhiz_sensor_entities = [
        HomeWhizSensorEntity(coordinator, control, entry.title, data)
        for control in sensor_controls
    ]
    _LOGGER.debug(
        "Entities: %s",
        {entity.entity_key: entity for entity in homewhiz_sensor_entities},
    )
    async_add_entities(homewhiz_sensor_entities)
