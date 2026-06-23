"""
Sub-entry flow for napoleon_bbq.

Handles adding a Napoleon Prestige grill to an existing Napoleon BBQ account
config entry. Each grill is stored as a sub-entry with its BLE MAC address,
Ayla DSN, and BLE local key.

Flow:
    1. ``async_step_user``: User enters account password and the grill's BLE MAC
       address. The username and region are taken from the parent config entry.
    2. Authentication → list all Prestige grills in the account → filter those
       already configured as sub-entries.
    3. If exactly one unconfigured grill is found, it is selected automatically.
    4. ``async_step_pick_device``: Shown when multiple unconfigured grills exist;
       the user selects which one to add.
    5. Sub-entry created with ``{CONF_MAC, CONF_DSN, CONF_LOCAL_KEY}``.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from custom_components.napoleon_bbq.api import (
    NapoleonBBQApiClient,
    NapoleonBBQApiClientAuthenticationError,
    NapoleonBBQApiClientCommunicationError,
    NapoleonBBQApiClientError,
)
from custom_components.napoleon_bbq.const import (
    AYLA_REGIONS,
    CONF_DSN,
    CONF_LOCAL_KEY,
    CONF_MAC,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_DEVICE,
)
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_REGION, CONF_USERNAME
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
        vol.Required(CONF_MAC): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="off")),
    }
)


class NapoleonBBQGrillSubentryFlowHandler(config_entries.ConfigSubentryFlow):
    """
    Sub-entry flow for adding a Napoleon Prestige grill to an account hub.

    Authenticates using the parent entry's stored username and region together
    with a password entered by the user. Discovers all unconfigured Prestige
    grills in the account and either auto-selects or presents a picker.

    """

    def __init__(self) -> None:
        """Initialise sub-entry flow state."""
        self._mac: str = ""
        self._devices: list[tuple[str, str]] = []  # [(dsn, display_name)]
        self._password: str = ""
        self._region_key: str = ""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.SubentryFlowResult:
        """
        Collect account password and grill MAC address.

        The parent config entry supplies the username and region. On successful
        authentication, filters out already-configured grills and either
        auto-selects the sole unconfigured grill or forwards to the device picker.

        Args:
            user_input: Form data submitted by the user, or None to show the form.

        Returns:
            A form, a pick-device step, or a created sub-entry result.

        """
        errors: dict[str, str] = {}
        entry = self._get_entry()

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            mac = user_input[CONF_MAC].upper().strip()
            username: str = entry.data[CONF_USERNAME]
            region_key: str = entry.data[CONF_REGION]

            # Reject MAC if already configured as a sub-entry anywhere in this domain.
            mac_lower = mac.lower()
            for domain_entry in self.hass.config_entries.async_entries(DOMAIN):
                for sub in domain_entry.subentries.values():
                    if sub.unique_id == mac_lower:
                        errors[CONF_MAC] = "already_configured"
                        return self.async_show_form(
                            step_id="user",
                            data_schema=_USER_SCHEMA,
                            errors=errors,
                        )

            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonBBQApiClient(region, session)
                all_devices = await client.async_list_devices(username, password)
            except NapoleonBBQApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonBBQApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonBBQApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon BBQ sub-entry setup")
                errors["base"] = "unknown"
            else:
                configured_dsns = {
                    sub.data[CONF_DSN]
                    for domain_entry in self.hass.config_entries.async_entries(DOMAIN)
                    for sub in domain_entry.subentries.values()
                    if sub.subentry_type == SUBENTRY_TYPE_DEVICE
                }
                available = [(dsn, name) for dsn, name in all_devices if dsn not in configured_dsns]

                if not available:
                    return self.async_abort(reason="no_devices_found")

                self._mac = mac
                self._devices = available
                self._password = password
                self._region_key = region_key

                if len(available) == 1:
                    dsn, name = available[0]
                    return await self._async_create_subentry(client, username, password, region_key, dsn, name)

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
            name = next((n for dsn, n in self._devices if dsn == selected_dsn), selected_dsn)
            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonBBQApiClient(region, session)
                return await self._async_create_subentry(
                    client, username, self._password, region_key, selected_dsn, name
                )
            except NapoleonBBQApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonBBQApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonBBQApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon BBQ device pick")
                errors["base"] = "unknown"

        options = [SelectOptionDict(value=dsn, label=name) for dsn, name in self._devices]
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
        client: NapoleonBBQApiClient,
        username: str,
        password: str,
        region_key: str,
        dsn: str,
        name: str,
    ) -> config_entries.SubentryFlowResult:
        """
        Fetch the local key for the selected DSN and create the sub-entry.

        Args:
            client: Authenticated API client.
            username: Napoleon app account email.
            password: Napoleon app account password (needed to sign in again).
            region_key: Ayla region identifier.
            dsn: Ayla device serial number of the selected grill.
            name: Display name for the sub-entry title.

        Returns:
            The created sub-entry flow result.

        """
        _, local_key = await client.async_get_local_key(username, password, dsn=dsn)
        return self.async_create_entry(
            title=name,
            data={
                CONF_MAC: self._mac,
                CONF_DSN: dsn,
                CONF_LOCAL_KEY: local_key,
            },
            unique_id=self._mac.lower(),
        )
