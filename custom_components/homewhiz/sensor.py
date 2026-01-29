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

# Fallback function-based controls for read-only devices (Air Quality Sensors, Issue #295)
# Maps function key -> (label, unit, icon, device_class)
FUNCTION_SENSORS = {
    # Numeric sensors
    "STT_CO2": ("CO2", "ppm", "mdi:molecule-co2", SensorDeviceClass.CO2),
    "STT_HUMIDITY": ("Humidity", "%", "mdi:water-percent", SensorDeviceClass.HUMIDITY),
    "STT_TEMPERATURE": ("Temperature", "°C", "mdi:thermometer", SensorDeviceClass.TEMPERATURE),
    "STT_RAW_HUMIDITY": ("Raw Humidity", "%", "mdi:water-outline", None),
    "STT_RAW_TEMPERATURE": ("Raw Temperature", "°C", "mdi:thermometer-lines", None),
    # Enum sensors (no unit!)
    "STT_CO2_LEVEL": ("CO2 Level", None, "mdi:air-filter", SensorDeviceClass.ENUM),
    "STT_HEALTH_STATUS": ("Health Status", None, "mdi:heart-pulse", SensorDeviceClass.ENUM),
    # Attribute sensors
    "ATR_BRIGHTNESS": ("Brightness", "%", "mdi:brightness-6", None),
    "ATR_SLEEP_MODE": ("Sleep Mode", None, "mdi:sleep", SensorDeviceClass.ENUM),
}


class HomeWhizSensorEntity(HomeWhizEntity, SensorEntity):
    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        control: (
            TimeControl
            | EnumControl
            | NumericControl
            | DebugControl
            | SummedTimestampControl
            | StateAwareRemainingTimeControl
        ),
        device_name: str,
        data: EntryData,
    ) -> None:
        super().__init__(coordinator, device_name, control.key, data)
        self._control = control

        if isinstance(control, (TimeControl, StateAwareRemainingTimeControl)):
            self._attr_icon = "mdi:clock-outline"
            self._attr_native_unit_of_measurement = "min"
            self._attr_device_class = SensorDeviceClass.DURATION

        elif isinstance(control, EnumControl):
            self._attr_device_class = SensorDeviceClass.ENUM  # type: ignore
            self._attr_options = list(self._control.options.values())  # type: ignore

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
    def native_value(self) -> float | int | str | datetime | None:  # type: ignore[override]
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
    """Sensor for read-only devices using functions array (e.g., Air Quality Sensors)."""

    _attr_has_entity_name = True

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
    def native_value(self) -> float | int | str | datetime | None:  # type: ignore[override]
        if self.coordinator.data is None:
            return None

        if isinstance(self.coordinator.data, dict):
            value = self.coordinator.data.get(self._function_key)
            if value is not None:
                _LOGGER.debug(
                    "Function %s value: %s", self._function_key, value
                )
            return value

        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up HomeWhiz sensor entities.
    
    Handles two device types:
    1. Read-only devices (config_missing=True): Air Quality Sensors, etc.
       - Creates function-based sensors from MQTT payload dict
       - No standard controls/programs
    
    2. Standard devices (config_missing=False): Washers, dryers, ovens, etc.
       - Creates control-based sensors from ProcAM config
       - Full program/monitoring support
    """
    data = build_entry_data(entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # ─────────────────────────────────────────────────────────────────────────
    # PATH 1: Read-only devices (Air Purifier, sensors without CONFIGURATION)
    # ─────────────────────────────────────────────────────────────────────────
    if entry.data.get("config_missing") is True:
        _LOGGER.info(
            "Setting up read-only device '%s' (config_missing=True) - using function-based sensors",
            entry.title,
        )
        # Function-based sensors for read-only devices
        function_sensors = [
            HomeWhizFunctionSensor(
                coordinator,
                entry.title,
                data,
                func_key,
                label,
                unit=unit,
                icon=icon,
                device_class=dev_class,
            )
            for func_key, (label, unit, icon, dev_class) in FUNCTION_SENSORS.items()
        ]

        if function_sensors:
            _LOGGER.info(
                "Created %d function-based sensors for read-only device '%s'",
                len(function_sensors),
                entry.title,
            )
            async_add_entities(function_sensors)
        else:
            _LOGGER.warning(
                "No function sensors defined for read-only device '%s' - check FUNCTION_SENSORS mapping",
                entry.title,
            )

        return  # CRITICAL: Early return prevents standard control generation!

    # ─────────────────────────────────────────────────────────────────────────
    # PATH 2: Standard devices with ProcAM configuration
    # ─────────────────────────────────────────────────────────────────────────
    _LOGGER.debug(
        "Setting up standard device '%s' (config_missing=False) - using ProcAM controls",
        entry.title,
    )

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

    _LOGGER.debug("Generated controls for '%s': %s", entry.title, controls)

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

    _LOGGER.debug(
        "Filtered sensor controls for '%s': %s",
        entry.title,
        [c.key for c in sensor_controls],
    )

    homewhiz_sensor_entities = [
        HomeWhizSensorEntity(coordinator, control, entry.title, data)
        for control in sensor_controls
    ]

    _LOGGER.debug(
        "Creating %d sensor entities for '%s': %s",
        len(homewhiz_sensor_entities),
        entry.title,
        {entity.entity_key: entity for entity in homewhiz_sensor_entities},
    )

    async_add_entities(homewhiz_sensor_entities)
