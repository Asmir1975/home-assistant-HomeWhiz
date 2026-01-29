import logging
from typing import Any

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_flow import EntryData
from .const import DOMAIN
from .homewhiz import HomewhizCoordinator

_LOGGER: logging.Logger = logging.getLogger(__package__)


# Compatibility: upstream currently uses "brandnamebycode" (defaultdict) [file:279]
try:
    from .homewhiz import brandnamebycode as _BRAND_MAP  # type: ignore
except Exception:  # pragma: no cover
    from .homewhiz import brand_name_by_code as _BRAND_MAP  # type: ignore


def build_device_info(unique_name: str, data: EntryData) -> DeviceInfo:
    friendly_name = (
        data.appliance_info.name if data.appliance_info is not None else unique_name
    )
    manufacturer = None
    if data.appliance_info is not None:
        try:
            manufacturer = _BRAND_MAP[data.appliance_info.brand]
        except Exception:
            manufacturer = None
    model = data.appliance_info.model if data.appliance_info is not None else None
    return DeviceInfo(  # type: ignore[typeddict-item]
        identifiers={(DOMAIN, unique_name)},
        name=friendly_name,
        manufacturer=manufacturer,
        model=model,
    )


def _extract_localization(contents: Any) -> dict[str, str]:
    """Extract localization dict from contents (handles both normal and debug mode)."""
    # Normal mode: ApplianceContents has .localization
    if hasattr(contents, "localization"):
        loc = getattr(contents, "localization")
        return loc if isinstance(loc, dict) else {}
    # Debug mode: contents is a dict like {"localization": {...}, "config": None}
    if isinstance(contents, dict):
        loc = contents.get("localization", {})
        return loc if isinstance(loc, dict) else {}
    return {}


class HomeWhizEntity(CoordinatorEntity[HomewhizCoordinator]):  # type: ignore[type-arg]
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HomewhizCoordinator,
        device_name: str,
        entity_key: str,
        data: EntryData,
    ) -> None:
        super().__init__(coordinator)
        self.entity_key = entity_key
        self._attr_unique_id = f"{device_name}_{entity_key}"
        self._attr_device_info = build_device_info(device_name, data)
        self._attr_device_class = f"{DOMAIN}__{entity_key}"
        self._localization: dict[str, str] = _extract_localization(data.contents)

    async def async_added_to_hass(self) -> None:
        """Call when the entity is added to hass."""
        await super().async_added_to_hass()
        if hasattr(self, "_control"):
            control = getattr(self, "_control")
            if hasattr(control, "my_entity_ids"):
                control.my_entity_ids.update({self.entity_id: self.name})
            else:
                setattr(control, "my_entity_ids", {self.entity_id: self.name})

    @property
    def available(self) -> bool:  # type: ignore[override]
        return self.coordinator.is_connected

    @property
    def translation_key(self) -> str | None:  # type: ignore[override]
        """Translation key for this entity.
        
        CRITICAL FIX: Use split("#") not split("_")!
        
        Examples:
        - "dryer_program" → "dryer_program" (no # present)
        - "variable#delay_start" → "variable" (for special entities)
        - "zone_1#hob_flexi" → "zone_1" (for zone entities)
        """
        return self.entity_key.lower().split("#")[0]
