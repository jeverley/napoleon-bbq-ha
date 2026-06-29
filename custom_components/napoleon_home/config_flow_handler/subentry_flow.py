"""
Sub-entry flow for napoleon_home.

Handles adding a Napoleon Prestige grill to an existing Napoleon Home account
config entry. Each grill is stored as a sub-entry with its BLE MAC address,
Ayla DSN, BLE local key, and local key ID.

Flow:
    1. ``async_step_user``: User enters account password. The username and region
       are taken from the parent config entry. The grill's MAC is obtained from the
       Ayla API device list rather than requiring manual entry.
    2. Authentication → list all Prestige grills in the account → filter those
       already configured as sub-entries.
    3. If exactly one unconfigured grill is found, it is selected automatically.
    4. ``async_step_pick_device``: Shown when multiple unconfigured grills exist;
       the user selects which one to add.
    5. Sub-entry created with ``{CONF_MAC, CONF_DSN, CONF_LOCAL_KEY, CONF_LOCAL_KEY_ID}``.
       The hub entry's stored Ayla token is updated with the fresh token.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.napoleon_home.api import (
    NapoleonHomeApiClient,
    NapoleonHomeApiClientAuthenticationError,
    NapoleonHomeApiClientCommunicationError,
    NapoleonHomeApiClientError,
)
from custom_components.napoleon_home.config_flow_handler.validate import async_validate_ble_key
from custom_components.napoleon_home.const import (
    AYLA_REGIONS,
    CONF_ACCESS_TOKEN,
    CONF_DSN,
    CONF_LOCAL_KEY,
    CONF_LOCAL_KEY_ID,
    CONF_MAC,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRY,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_DEVICE,
)
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_REGION, CONF_USERNAME
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class NapoleonHomeGrillSubentryFlowHandler(config_entries.ConfigSubentryFlow):
    """
    Sub-entry flow for adding a Napoleon Prestige grill to an account hub.

    Authenticates using the parent entry's stored username and region together
    with a password entered by the user. Discovers all unconfigured Prestige
    grills in the account and either auto-selects or presents a picker.
    The grill's MAC address is obtained from the Ayla API device list.

    """

    def __init__(self) -> None:
        """Initialise sub-entry flow state."""
        self._devices: list[tuple[str, str, str]] = []  # [(dsn, display_name, mac)]
        self._password: str = ""
        self._region_key: str = ""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """
        Collect account password and authenticate with the Ayla cloud.

        The parent config entry supplies the username and region. On successful
        authentication, filters out already-configured grills and either
        auto-selects the sole unconfigured grill or forwards to the device picker.
        The grill's MAC address is obtained from the API device list.

        Args:
            user_input: Form data submitted by the user, or None to show the form.

        Returns:
            A form, a pick-device step, or a created sub-entry result.

        """
        errors: dict[str, str] = {}
        entry = self._get_entry()

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            username: str = entry.data[CONF_USERNAME]
            region_key: str = entry.data[CONF_REGION]

            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, session)
                all_devices, _token, _refresh, _expiry = await client.async_list_devices(username, password)
            except NapoleonHomeApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonHomeApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonHomeApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon Home sub-entry setup")
                errors["base"] = "unknown"
            else:
                configured_dsns = {
                    sub.data[CONF_DSN]
                    for domain_entry in self.hass.config_entries.async_entries(DOMAIN)
                    for sub in domain_entry.subentries.values()
                    if sub.subentry_type == SUBENTRY_TYPE_DEVICE
                }
                available: list[tuple[str, str, str]] = []
                for dsn, name, mac in all_devices:
                    if dsn in configured_dsns:
                        continue
                    if not mac:
                        LOGGER.warning(
                            "Napoleon Home: skipping DSN=%s in sub-entry flow because Ayla returned no MAC",
                            dsn,
                        )
                        continue
                    available.append((dsn, name, mac))

                if not available:
                    return self.async_abort(reason="no_devices_found")

                self._devices = available
                self._password = password
                self._region_key = region_key

                if len(available) == 1:
                    dsn, name, mac = available[0]
                    try:
                        return await self._async_create_subentry(client, username, password, region_key, dsn, name, mac)
                    except ConfigEntryAuthFailed:
                        errors["base"] = "invalid_auth"
                    except HomeAssistantError:
                        errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_pick_device()

        return self.async_show_form(
            step_id="user",
            data_schema=_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_pick_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """
        Let the user select which Ayla grill to add when multiple are available.

        Args:
            user_input: Form data with ``CONF_DSN`` selected, or None to show form.

        Returns:
            A form result or the created sub-entry result.

        """
        errors: dict[str, str] = {}
        entry = self._get_entry()
        username: str = entry.data[CONF_USERNAME]
        region_key: str = self._region_key or entry.data[CONF_REGION]

        if user_input is not None:
            selected_dsn = user_input[CONF_DSN]
            name = next((n for dsn, n, _mac in self._devices if dsn == selected_dsn), selected_dsn)
            mac = next((_mac for dsn, _n, _mac in self._devices if dsn == selected_dsn), "")
            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, session)
                return await self._async_create_subentry(
                    client, username, self._password, region_key, selected_dsn, name, mac
                )
            except NapoleonHomeApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonHomeApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonHomeApiClientError:
                errors["base"] = "unknown"
            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except HomeAssistantError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon Home device pick")
                errors["base"] = "unknown"

        options = [SelectOptionDict(value=dsn, label=name) for dsn, name, _mac in self._devices]
        schema = vol.Schema(
            {
                vol.Required(CONF_DSN): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(
            step_id="pick_device",
            data_schema=schema,
            errors=errors,
        )

    async def _async_create_subentry(
        self,
        client: NapoleonHomeApiClient,
        username: str,
        password: str,
        region_key: str,
        dsn: str,
        name: str,
        mac: str,
    ) -> config_entries.SubentryFlowResult:
        """
        Fetch the local key, validate it via BLE, and create the sub-entry.

        Validates the BLE key before creating the sub-entry. Updates the hub
        entry with fresh Ayla tokens obtained during the key fetch.

        Args:
            client: API client instance.
            username: Napoleon app account email.
            password: Napoleon app account password.
            region_key: Ayla region identifier (stored for reference).
            dsn: Ayla device serial number of the selected grill.
            name: Display name for the sub-entry title.
            mac: BLE MAC address from the Ayla API (``"AA:BB:CC:DD:EE:FF"``).

        Returns:
            The created sub-entry flow result.

        Raises:
            ConfigEntryAuthFailed: If BLE key validation is rejected (s:4).
            HomeAssistantError: If BLE key validation fails or times out.
            NapoleonHomeApiClientError: If the local key cannot be fetched from Ayla.

        """
        _, local_key, local_key_id, access_token, refresh_token, token_expiry = await client.async_get_local_key(
            username, password, dsn=dsn
        )

        if not mac:
            msg = f"Napoleon Home {dsn}: cannot add sub-entry without BLE MAC"
            raise HomeAssistantError(msg)

        if mac:
            await async_validate_ble_key(self.hass, mac, local_key)

        entry = self._get_entry()
        self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: refresh_token,
                CONF_TOKEN_EXPIRY: token_expiry,
            },
        )
        return self.async_create_entry(
            title=name,
            data={
                CONF_MAC: mac,
                CONF_DSN: dsn,
                CONF_LOCAL_KEY: local_key,
                CONF_LOCAL_KEY_ID: local_key_id,
            },
            unique_id=mac.lower(),
        )
