from __future__ import annotations

import logging
from typing import Any

from dacite import from_dict
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import REVOLUTIONS_PER_MINUTE, UnitOfTemperature

from custom_components.homewhiz import IdExchangeResponse
from custom_components.homewhiz.api import ApplianceContents, ApplianceInfo
from custom_components.homewhiz.appliance_config import ApplianceConfiguration
from custom_components.homewhiz.config_flow import CloudConfig, EntryData

_LOGGER: logging.Logger = logging.getLogger(__package__)


def build_entry_data(entry: ConfigEntry) -> EntryData:
    """Build EntryData from ConfigEntry storage data.
    
    CRITICAL FIX (Issue #295):
    - Storage contains serialized dict, not ApplianceContents object
    - Must reconstruct ApplianceContents from dict for backward compatibility
    """
    entry_data = entry.data

    # Reconstruct IdExchangeResponse
    ids = from_dict(IdExchangeResponse, entry_data["ids"])

    # Reconstruct CloudConfig (can be None)
    cloud_config = None
    if entry_data.get("cloud_config") is not None:
        cloud_config = from_dict(CloudConfig, entry_data["cloud_config"])

    # CRITICAL: Reconstruct ApplianceContents from serialized dict
    # Storage format: {"config": {...}, "localization": {...}}
    contents_dict = entry_data["contents"]
    
    if isinstance(contents_dict, dict):
        # Reconstruct ApplianceConfiguration from nested dict
        config_dict = contents_dict.get("config")
        
        if config_dict is not None and isinstance(config_dict, dict):
            try:
                config = from_dict(ApplianceConfiguration, config_dict)
            except Exception as err:
                _LOGGER.warning(
                    "Failed to deserialize ApplianceConfiguration for entry %s: %s - using minimal config",
                    entry.entry_id,
                    err,
                )
                # Fallback: minimal config for read-only devices
                config = from_dict(ApplianceConfiguration, {
                    "appliances": [],
                    "functions": [],
                    "controls": [],
                })
        else:
            # No config (read-only device like AQ sensor)
            config = from_dict(ApplianceConfiguration, {
                "appliances": [],
                "functions": [],
                "controls": [],
            })
        
        localization = contents_dict.get("localization", {})
        
        # Reconstruct ApplianceContents object
        contents = ApplianceContents(
            config=config,
            localization=localization,
        )
    else:
        # Backward compatibility: Try to deserialize directly as ApplianceContents
        try:
            contents = from_dict(ApplianceContents, contents_dict)
        except Exception as err:
            _LOGGER.error(
                "Failed to deserialize contents for entry %s: %s - creating minimal config",
                entry.entry_id,
                err,
            )
            # Create minimal ApplianceContents
            contents = ApplianceContents(
                config=from_dict(ApplianceConfiguration, {
                    "appliances": [],
                    "functions": [],
                    "controls": [],
                }),
                localization={},
            )

    # Get appliance_info (can be None)
    appliance_info = None
    if entry_data.get("appliance_info") is not None:
        appliance_info = from_dict(ApplianceInfo, entry_data["appliance_info"])

    # Get config_missing flag (default False for backward compatibility)
    config_missing = entry_data.get("config_missing", False)

    return EntryData(
        ids=ids,
        contents=contents,  # Now always ApplianceContents object
        appliance_info=appliance_info,
        cloud_config=cloud_config,
        config_missing=config_missing,
    )


def unit_for_key(key: str) -> str | None:
    if "temp" in key:
        return UnitOfTemperature.CELSIUS
    if "spin" in key:
        return REVOLUTIONS_PER_MINUTE
    return None


def icon_for_key(key: str) -> str | None:
    if "temp" in key:
        return "mdi:thermometer"
    if "spin" in key:
        return "mdi:rotate-3d-variant"
    return None
