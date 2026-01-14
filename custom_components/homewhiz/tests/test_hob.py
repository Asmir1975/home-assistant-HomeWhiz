import json
from pathlib import Path
from unittest import TestCase

import pytest
from dacite import from_dict

from custom_components.homewhiz.appliance_config import ApplianceConfiguration
from custom_components.homewhiz.appliance_controls import generate_controls_from_config

test_case = TestCase()
test_case.maxDiff = None


@pytest.fixture
def config() -> ApplianceConfiguration:
    file_path = Path(__file__).parent / "fixtures" / "example_hob_config.json"
    with file_path.open() as file:
        json_content = json.load(file)
        return from_dict(ApplianceConfiguration, json_content)


def test_hob_controls_generation(config: ApplianceConfiguration) -> None:
    """Test that all expected hob controls are generated from config."""
    controls = generate_controls_from_config("test_hob", config)
    control_keys = [control.key for control in controls]

    expected_keys = [
        # Global device state
        "state",
        # HobToHood monitoring
        "monitoring_hob2hood",
        # Settings
        "settings_hob2hood",
        "settings_keylocked",
    ]

    # Zone-specific controls (4 zones × controls per zone)
    for zone_num in range(1, 5):
        expected_keys.extend(
            [
                f"zone_{zone_num}_program",
                f"zone_{zone_num}_hob_predefined_program",
                f"zone_{zone_num}_hob_heater_level",
                f"zone_{zone_num}_hob_flexi",
                f"zone_{zone_num}_zone_extended",
                f"zone_{zone_num}_cooking_state",
                f"zone_{zone_num}_duration",
                f"zone_{zone_num}_hob_hot",
                f"zone_{zone_num}_hob_pan_info",
            ]
        )

    test_case.assertListEqual(control_keys, expected_keys)


def test_hob_optional_fields(config: ApplianceConfiguration) -> None:
    """Test that optional allowedTransitions and notificationInfo fields work correctly.

    This is the core fix for Issue #352 - hob configs don't have these fields.
    """
    # Check device states have optional allowedTransitions
    if config.deviceStates and config.deviceStates.states:
        for state in config.deviceStates.states:
            # Should not raise AttributeError even when field is missing
            assert hasattr(state, "allowedTransitions")
            # For hobs, this is typically None
            assert state.allowedTransitions is None

        # Check that notificationInfo exists (but can be None for some states)
        assert config.deviceStates.states[0].notificationInfo is not None
        assert (
            config.deviceStates.states[0].notificationInfo.strKey
            == "DEVICE_STATE_ON_NOTIFICATION"
        )


def test_hob_zones_structure(config: ApplianceConfiguration) -> None:
    """Test that zone configuration is correctly parsed."""
    assert config.zones is not None
    assert config.zones.numberOfZones == 4
    assert config.zones.firstZoneWifiArrayStartIndex == 39
    assert config.zones.eachZoneWifiArraySegmentLength == 21

    # Test default zone structure
    if config.zones.defaultZone:
        default_zone = config.zones.defaultZone
        assert default_zone.program is not None
        assert default_zone.program.values is not None
        assert len(default_zone.program.values) == 2  # Manual and Predefined
        assert default_zone.subPrograms is not None
        assert (
            len(default_zone.subPrograms) == 3
        )  # Predefined program, Heater level, FlexiZone


def test_hob_no_write_access(config: ApplianceConfiguration) -> None:
    """Test that hob controls are read-only (wfaWriteIndex is None).

    This documents the security design - no remote cooking for safety reasons.
    """
    # Check settings have no write index
    if config.settings:
        for setting in config.settings:
            assert setting.wfaWriteIndex is None

    # Check zone program has no write index
    if config.zones and config.zones.defaultZone:
        default_zone = config.zones.defaultZone
        if default_zone.program:
            assert default_zone.program.wfaWriteIndex is None

        # Check all sub-programs have no write index
        if default_zone.subPrograms:
            for sub_program in default_zone.subPrograms:
                assert sub_program.wfaWriteIndex is None


def test_hob_binary_sensors(config: ApplianceConfiguration) -> None:
    """Test that hob warning sensors (hot surface, pan detection) are correctly parsed."""
    if config.zones and config.zones.defaultZone:
        default_zone = config.zones.defaultZone
        if default_zone.deviceWarnings and default_zone.deviceWarnings.warnings:
            warnings = default_zone.deviceWarnings.warnings

            assert len(warnings) == 2
            assert warnings[0].strKey == "HOB_HOT"
            assert warnings[1].strKey == "HOB_PAN_INFO"

            # Both should have notification info
            assert warnings[0].notificationInfo is not None
            assert warnings[0].notificationInfo.strKey == "HOB_HOT_NOTIFICATION"
            assert warnings[1].notificationInfo is not None
            assert warnings[1].notificationInfo.strKey == "HOB_PAN_INFO_NOTIFICATION"


def test_hob_flexi_zone_switch(config: ApplianceConfiguration) -> None:
    """Test that FlexiZone control is correctly identified as a switch."""
    if config.zones and config.zones.defaultZone:
        default_zone = config.zones.defaultZone
        if default_zone.subPrograms:
            flexi_control = next(
                sp for sp in default_zone.subPrograms if sp.strKey == "HOB_FLEXI"
            )

            assert flexi_control.isSwitch == 1
            assert flexi_control.enumValues is not None
            assert len(flexi_control.enumValues) == 2  # OFF and ON
