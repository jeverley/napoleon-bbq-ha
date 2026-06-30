"""
Options flow for napoleon_home.

This module implements the options flow that allows users to modify integration
settings and manage grills after initial configuration.

Available actions:
    settings:     Adjust poll interval.
    add_grill:    Authenticate with Napoleon account and add another grill.
    remove_grill: Select and remove a configured grill.

For more information:
https://developers.home-assistant.io/docs/config_entries_options_flow_handler
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
from custom_components.napoleon_home.config_flow_handler.schemas import get_options_schema
from custom_components.napoleon_home.const import (
    AYLA_REGIONS,
    CONF_ACCESS_TOKEN,
    CONF_DEVICES,
    CONF_DSN,
    CONF_LOCAL_KEY,
    CONF_LOCAL_KEY_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRY,
    DOMAIN,
    LOGGER,
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

_PASSWORD_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


class NapoleonHomeOptionsFlow(config_entries.OptionsFlow):
    """
    Handle the options flow for napoleon_home.

    Presents a menu with three choices: adjust settings, add a grill, or remove
    a grill. Add-grill authenticates with the stored account credentials (plus a
    re-entered password) and adds the selected device to ``entry.data[CONF_DEVICES]``.
    Remove-grill presents a picker and deletes the selected device.

    """

    def __init__(self) -> None:
        """Initialise options flow state."""
        self._devices: list[tuple[str, str, str]] = []  # [(dsn, name, mac)]
        self._password: str = ""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "add_grill", "remove_grill"],
        )

    async def async_step_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Manage the poll interval setting."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="settings",
            data_schema=get_options_schema(self.config_entry.options),
        )

    async def async_step_add_grill(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Authenticate and discover unconfigured grills to add."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        username: str = entry.data[CONF_USERNAME]
        region_key: str = entry.data[CONF_REGION]

        if user_input is not None:
            password = user_input[CONF_PASSWORD]

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
                LOGGER.exception("Unexpected exception during Napoleon Home add grill")
                errors["base"] = "unknown"
            else:
                configured_dsns = {
                    d[CONF_DSN]
                    for domain_entry in self.hass.config_entries.async_entries(DOMAIN)
                    for d in domain_entry.data.get(CONF_DEVICES, {}).values()
                    if d.get(CONF_DSN)
                }
                available: list[tuple[str, str, str]] = [
                    (dsn, name, mac) for dsn, name, mac in all_devices if dsn not in configured_dsns and mac
                ]

                if not available:
                    return self.async_abort(reason="no_devices_found")

                self._devices = available
                self._password = password

                if len(available) == 1:
                    dsn, name, mac = available[0]
                    try:
                        return await self._async_create_device(client, username, password, region_key, dsn, name, mac)
                    except ConfigEntryAuthFailed:
                        errors["base"] = "invalid_auth"
                    except HomeAssistantError:
                        errors["base"] = "cannot_connect"
                else:
                    return await self.async_step_pick_grill()

        return self.async_show_form(
            step_id="add_grill",
            data_schema=_PASSWORD_SCHEMA,
            errors=errors,
            description_placeholders={"username": username},
        )

    async def async_step_pick_grill(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Let the user select which grill to add when multiple are available."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        username: str = entry.data[CONF_USERNAME]
        region_key: str = entry.data[CONF_REGION]

        if user_input is not None:
            selected_dsn = user_input[CONF_DSN]
            name = next((n for dsn, n, _mac in self._devices if dsn == selected_dsn), selected_dsn)
            mac = next((_mac for dsn, _n, _mac in self._devices if dsn == selected_dsn), "")
            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, session)
                return await self._async_create_device(
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
                LOGGER.exception("Unexpected exception during Napoleon Home grill pick")
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
            step_id="pick_grill",
            data_schema=schema,
            errors=errors,
        )

    async def _async_create_device(
        self,
        client: NapoleonHomeApiClient,
        username: str,
        password: str,
        region_key: str,
        dsn: str,
        name: str,
        mac: str,
    ) -> config_entries.ConfigFlowResult:
        """Fetch the local key and add the grill to entry.data[CONF_DEVICES]."""
        _, local_key, local_key_id, access_token, refresh_token, token_expiry = await client.async_get_local_key(
            username, password, dsn=dsn
        )

        if not mac:
            msg = f"Napoleon Home {dsn}: cannot add grill without BLE MAC"
            raise HomeAssistantError(msg)

        entry = self.config_entry
        updated_devices = {
            **entry.data.get(CONF_DEVICES, {}),
            mac: {
                CONF_DSN: dsn,
                CONF_LOCAL_KEY: local_key,
                CONF_LOCAL_KEY_ID: local_key_id,
                "name": name,
            },
        }
        self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: refresh_token,
                CONF_TOKEN_EXPIRY: token_expiry,
                CONF_DEVICES: updated_devices,
            },
        )
        await self.hass.config_entries.async_reload(entry.entry_id)
        return self.async_abort(reason="grill_added")

    async def async_step_remove_grill(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Select a configured grill to remove."""
        entry = self.config_entry
        devices = entry.data.get(CONF_DEVICES, {})

        if not devices:
            return self.async_abort(reason="no_devices_found")

        if user_input is not None:
            mac_to_remove = user_input["mac"]
            updated_devices = {mac: d for mac, d in devices.items() if mac != mac_to_remove}
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_DEVICES: updated_devices},
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="grill_removed")

        options = [SelectOptionDict(value=mac, label=d.get("name", mac)) for mac, d in devices.items()]
        schema = vol.Schema(
            {
                vol.Required("mac"): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                ),
            }
        )
        return self.async_show_form(
            step_id="remove_grill",
            data_schema=schema,
        )


__all__ = ["NapoleonHomeOptionsFlow"]
