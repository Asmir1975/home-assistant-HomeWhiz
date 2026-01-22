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

########################################################################################################
# Function-based sensors for exotic (read-only) devices (e.g. Air Purifier, Issue #295):
# - Maps function key (e.g. STT_CO2) to label, unit, icon, device_class
# - Used only if no real config is present (config_missing=True)
# - See async_setup_entry for activation logic
########################################################################################################
FUNCTION_SENSORS = {
    "STT_CO2": ("CO2", "ppm", "mdi:molecule-co2", SensorDeviceClass.CO2),
    "STT_HUMIDITY": ("Humidity", "%", "mdi:water-percent", None),
    "STT_TEMPERATURE": ("Temperature", "°C", "mdi:thermometer", None),
    "STT_RAW_HUMIDITY": ("Raw Humidity", "%", "mdi:water-outline", None),
    "STT_RAW_TEMPERATURE": ("Raw Temperature", "°C", "mdi:thermometer-lines", None),
    "STT_CO2_LEVEL": ("CO2 Level", None, None, SensorDeviceClass.ENUM),
    "STT_HEALTH_STATUS": ("Health Status", None, None, SensorDeviceClass.ENUM),
    "ATR_BRIGHTNESS": ("Brightness", None, "mdi:brightness-6", None),
    "ATR_SLEEP_MODE": ("Sleep Mode", None, "mdi:sleep", None),
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
    """Sensor for read-only devices using functions array (e.g., TR AirPurifier)."""

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


class HomeWhizRawHexHeadSensor(HomeWhizEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        device_name: str,
        data: EntryData,
        start: int = 0,
        length: int = 120,
    ) -> None:
        super().__init__(coordinator, device_name, "RAW_HEX_HEAD", data)
        self._start = start
        self._length = length
        self._attr_icon = "mdi:code-tags"

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        if self.coordinator.data is None:
            return None

        # Handle both dict and bytearray
        if isinstance(self.coordinator.data, dict):
            return None  # Functions don't have hex representation

        raw = self.coordinator.data
        s = min(max(self._start, 0), len(raw))
        e = min(s + max(self._length, 0), len(raw))
        return raw[s:e].hex()

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:  # type: ignore[override]
        if self.coordinator.data is None:
            return None

        # Only for bytearray, not dict
        if isinstance(self.coordinator.data, dict):
            return None

        raw = self.coordinator.data
        return {
            "len": len(raw),
            "hex_full": raw.hex(),
        }


class HomeWhizRawLenSensor(HomeWhizEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        device_name: str,
        data: EntryData,
    ) -> None:
        super().__init__(coordinator, device_name, "RAW_LEN", data)
        self._attr_icon = "mdi:counter"
        self._attr_native_unit_of_measurement = "bytes"

    @property
    def native_value(self) -> int | None:  # type: ignore[override]
        if self.coordinator.data is None:
            return None

        if isinstance(self.coordinator.data, dict):
            return len(self.coordinator.data)

        return len(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = build_entry_data(entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    # Debug-mode for Air Purifier (config_missing=True): no ProcAM config -> show raw payloads
    if entry.data.get("config_missing") is True:
        # Many payloads are padded to offset=26 in cloud.py; showing from 0 is still useful.
        async_add_entities(
            [
                HomeWhizRawLenSensor(coordinator, entry.title, data),
                HomeWhizRawHexHeadSensor(
                    coordinator, entry.title, data, start=0, length=160
                ),
            ]
        )

        # NEW: Add function-based sensors for read-only devices
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
                "Created %d function-based sensors for read-only device",
                len(function_sensors),
            )
            async_add_entities(function_sensors)

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
