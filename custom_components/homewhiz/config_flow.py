import logging
from dataclasses import asdict, dataclass
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_ADDRESS, CONF_ID, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import (
    ApplianceInfo,
    ContentsIndexResponse,
    IdExchangeResponse,
    LoginError,
    LoginResponse,
    RequestError,
    fetch_appliance_contents,
    fetch_appliance_infos,
    fetch_base_contents_index,
    fetch_localizations_contents_index,
    login,
    make_id_exchange_request,
)
from .const import CONF_BT_RECONNECT_INTERVAL, DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__package__)


@dataclass
class CloudConfig:
    username: str
    password: str


@dataclass
class EntryData:
    ids: IdExchangeResponse
    contents: Any
    appliance_info: ApplianceInfo | None
    cloud_config: CloudConfig | None
    config_missing: bool = False  # FIX Issue #295


def has_real_config(contents: Any) -> bool:
    """Check if device has real ProcAM config (Issue #295)."""
    config = contents.config
    return (
        getattr(config, "program", None) is not None
        or (getattr(config, "subPrograms", None) is not None and len(config.subPrograms) > 0)
        or (getattr(config, "monitorings", None) is not None and len(config.monitorings) > 0)
        or getattr(config, "deviceStates", None) is not None
        or getattr(config, "commands", None) is not None
    )


class TiltConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for HomeWhiz"""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_bt_devices: dict[str, str] = {}
        self._bt_address: str | None = None
        self._bt_name: str | None = None

        self._cloud_config: CloudConfig | None = None
        self._cloud_credentials: LoginResponse | None = None
        self._cloud_appliances: list[ApplianceInfo] | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if not discovery_info.name.startswith("HwZ"):
            return self.async_abort(reason="not_supported")

        self._bt_address = discovery_info.address
        self._bt_name = discovery_info.name
        return await self.async_step_bluetooth_connect()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["select_bluetooth_device", "provide_cloud_credentials"],
        )

    async def async_step_select_bluetooth_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            self._bt_address = address
            self._bt_name = self._discovered_bt_devices[address]
            return await self.async_step_bluetooth_connect()

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_bt_devices:
                continue
            if discovery_info.name.startswith("HwZ"):
                self._discovered_bt_devices[address] = discovery_info.name

        if len(self._discovered_bt_devices) == 0:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="select_bluetooth_device",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._discovered_bt_devices)}),
        )

    async def async_step_bluetooth_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._bt_address is not None
            assert self._bt_name is not None

            await self.async_set_unique_id(self._bt_address)
            self._abort_if_unique_id_configured()

            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            try:
                credentials = await login(username, password)
                id_response = await make_id_exchange_request(self._bt_name)

                contents = await fetch_appliance_contents(credentials, id_response.appId)
                appliance_infos = await fetch_appliance_infos(credentials)
                appliance_info = next(
                    (ai for ai in appliance_infos if ai.applianceId == id_response.appId),
                    None,
                )

                _has_config = has_real_config(contents)
                if not _has_config:
                    _LOGGER.warning(
                        "Device %s has no config - using functions (Issue #295)",
                        id_response.appId,
                    )

                data = EntryData(
                    ids=id_response,
                    contents=contents,
                    appliance_info=appliance_info,
                    cloud_config=None,
                    config_missing=not _has_config,
                )
                return self.async_create_entry(
                    title=appliance_info.name if appliance_info is not None else self._bt_name,
                    data=asdict(data),
                )

            except LoginError:
                errors["base"] = "invalid_auth"
            except RequestError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="bluetooth_connect",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)  # type: ignore[typeddict-item]
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_provide_cloud_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            try:
                credentials = await login(username, password)
                self._cloud_config = CloudConfig(username, password)
                self._cloud_credentials = credentials
                return await self.async_step_select_cloud_device()
            except LoginError:
                errors["base"] = "invalid_auth"
            except RequestError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="provide_cloud_credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)  # type: ignore[typeddict-item]
                    ),
                }
            ),
            errors=errors,
        )

    async def _fetch_localization_only(self, credentials: LoginResponse) -> dict[str, str]:
        idx: ContentsIndexResponse = await fetch_base_contents_index(credentials, "en-GB")
        return await fetch_localizations_contents_index(idx)

    async def async_step_select_cloud_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._cloud_credentials is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            assert self._cloud_appliances is not None
            appliance_id = user_input[CONF_ID]

            await self.async_set_unique_id(appliance_id)
            self._abort_if_unique_id_configured()

            appliance = next(a for a in self._cloud_appliances if a.applianceId == appliance_id)

            try:
                contents = await fetch_appliance_contents(
                    self._cloud_credentials, appliance_id
                )

                _has_config = has_real_config(contents)
                if not _has_config:
                    _LOGGER.warning(
                        "Device %s has no config - using functions (Issue #295)",
                        appliance_id,
                    )

                data = EntryData(
                    ids=IdExchangeResponse(appliance_id),
                    contents=contents,
                    appliance_info=appliance,
                    cloud_config=self._cloud_config,
                    config_missing=not _has_config,
                )
                return self.async_create_entry(
                    title=appliance.name,
                    data=asdict(data),
                )

            except RequestError as err:
                # Debug mode for missing CONFIGURATION: create entry with localization only
                _LOGGER.debug("fetch_appliance_contents failed for %s: %s", appliance_id, err)
                try:
                    localization = await self._fetch_localization_only(self._cloud_credentials)
                    data = EntryData(
                        ids=IdExchangeResponse(appliance_id),
                        contents={"localization": localization, "config": None},
                        appliance_info=appliance,
                        cloud_config=self._cloud_config,
                        config_missing=True,
                    )
                    return self.async_create_entry(title=appliance.name, data=asdict(data))
                except RequestError:
                    errors["base"] = "cannot_connect"

        if self._cloud_appliances is None:
            try:
                self._cloud_appliances = await fetch_appliance_infos(self._cloud_credentials)
            except RequestError:
                errors["base"] = "cannot_connect"
                self._cloud_appliances = []

        if len(self._cloud_appliances) == 0:
            return self.async_abort(reason="no_devices_found")

        options = {a.applianceId: a.name for a in self._cloud_appliances if not a.is_bt()}
        return self.async_show_form(
            step_id="select_cloud_device",
            data_schema=vol.Schema({vol.Required(CONF_ID): vol.In(options)}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        if config_entry.data["cloud_config"] is not None:
            return CloudOptionsFlowHandler()
        return BluetoothOptionsFlowHandler()


class CloudOptionsFlowHandler(OptionsFlow):
    def __init__(self) -> None:
        """Initialize options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))


class BluetoothOptionsFlowHandler(OptionsFlow):
    def __init__(self) -> None:
        """Initialize options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            _LOGGER.debug("Reloading entries after updating options: %s", user_input)
            self.hass.config_entries.async_update_entry(self.config_entry, options=user_input)
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BT_RECONNECT_INTERVAL,
                        description={
                            "suggested_value": self.config_entry.options.get(CONF_BT_RECONNECT_INTERVAL, None)
                        },
                    ): cv.positive_int,
                }
            ),
        )
