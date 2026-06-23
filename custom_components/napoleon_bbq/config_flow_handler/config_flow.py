"""
Config flow for napoleon_bbq.

This module implements the configuration flow for initial hub setup via BLE
discovery or manual entry, plus reauthentication when local keys need refreshing.

The integration uses a hub model: one config entry per Napoleon account, with
one sub-entry per Napoleon Prestige grill. Each sub-entry stores the grill's
BLE MAC address, Ayla DSN, and BLE local key.

Setup flow (BLE discovery — primary path):
    1. ``async_step_bluetooth``: Grill advertisement fires. MAC checked against
       existing sub-entries; aborts if already configured.
    2. ``async_step_user``: User enters Napoleon account credentials and region.
    3. Ayla cloud auth → list all Prestige grills in the account.
    4. If one grill: auto-selected. If multiple: ``async_step_pick_device``.
    5. Local key fetched for the selected DSN.
    6. If an account hub entry already exists: grill added as sub-entry and
       flow aborts with "device_added_to_account".
    7. If no hub entry: main entry created with the grill as the first sub-entry.

Setup flow (manual — fallback when grill is not advertising):
    1. ``async_step_user``: User enters MAC, credentials, and region.
    2. Same Ayla cloud steps as above.

Reauth flow:
    - Triggered when a coordinator raises ``ConfigEntryAuthFailed``.
    - User re-enters credentials; local keys are refreshed for ALL sub-entries
      in the hub in a single sign-in round-trip.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from custom_components.napoleon_bbq.api import (
    NapoleonBBQApiClient,
    NapoleonBBQApiClientAuthenticationError,
    NapoleonBBQApiClientCommunicationError,
    NapoleonBBQApiClientError,
)
from custom_components.napoleon_bbq.const import (
    AYLA_DEFAULT_REGION,
    AYLA_REGION_EU,
    AYLA_REGION_US,
    AYLA_REGIONS,
    CONF_DSN,
    CONF_LOCAL_KEY,
    CONF_MAC,
    DOMAIN,
    LOGGER,
    SUBENTRY_TYPE_DEVICE,
)
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
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

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.config_flow_handler.options_flow import NapoleonBBQOptionsFlow
    from custom_components.napoleon_bbq.config_flow_handler.subentry_flow import NapoleonBBQGrillSubentryFlowHandler

_REGION_OPTIONS = [
    SelectOptionDict(value=AYLA_REGION_EU, label="Europe"),
    SelectOptionDict(value=AYLA_REGION_US, label="United States"),
]

_CREDENTIALS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
        vol.Required(CONF_REGION, default=AYLA_DEFAULT_REGION): SelectSelector(
            SelectSelectorConfig(
                options=_REGION_OPTIONS,
                mode=SelectSelectorMode.LIST,
            )
        ),
    }
)

_USER_SCHEMA_WITH_MAC = _CREDENTIALS_SCHEMA.extend(
    {
        vol.Required(CONF_MAC): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="off")),
    }
)


class NapoleonBBQConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for napoleon_bbq.

    Creates a hub config entry (one per Napoleon account) with the first
    Napoleon Prestige grill as a sub-entry. Additional grills can be added
    via BLE discovery or through the sub-entry flow (options → add grill).

    Supports BLE discovery (primary path) and manual entry (fallback), plus
    reauthentication for refreshing expired local keys across all sub-entries.

    Attributes:
        VERSION: Config entry schema major version.
        MINOR_VERSION: Config entry schema minor version.

    """

    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[NapoleonBBQGrillSubentryFlowHandler]]:
        """
        Return the sub-entry types supported by this integration.

        Args:
            config_entry: The existing hub config entry.

        Returns:
            A dict mapping ``SUBENTRY_TYPE_DEVICE`` to the grill sub-entry flow handler.

        """
        from custom_components.napoleon_bbq.config_flow_handler.subentry_flow import (  # noqa: PLC0415
            NapoleonBBQGrillSubentryFlowHandler,
        )

        return {SUBENTRY_TYPE_DEVICE: NapoleonBBQGrillSubentryFlowHandler}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NapoleonBBQOptionsFlow:
        """
        Get the options flow for modifying integration settings.

        Args:
            config_entry: The existing config entry for this integration instance.

        Returns:
            The options flow instance.

        """
        from custom_components.napoleon_bbq.config_flow_handler.options_flow import (  # noqa: PLC0415
            NapoleonBBQOptionsFlow,
        )

        return NapoleonBBQOptionsFlow()

    def __init__(self) -> None:
        """Initialise the config flow with no pre-discovered device state."""
        self._mac: str | None = None
        self._name: str | None = None
        self._devices: list[tuple[str, str]] = []  # [(dsn, display_name)]
        self._username: str = ""
        self._password: str = ""
        self._region_key: str = ""

    async def async_step_bluetooth(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> config_entries.ConfigFlowResult:
        """
        Handle BLE advertisement discovery of a Napoleon Prestige grill.

        Checks whether the discovered MAC is already configured as a sub-entry
        across any existing hub entry. If so, aborts. Otherwise stores the MAC
        and forwards to the user credential step.

        Args:
            discovery_info: BLE advertisement data from the HA Bluetooth integration.

        Returns:
            A config flow result forwarding to the user step for credential entry.

        """
        mac_lower = discovery_info.address.lower()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for sub in entry.subentries.values():
                if sub.unique_id == mac_lower:
                    return self.async_abort(reason="already_configured")

        self._mac = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}

        return await self.async_step_user()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Handle credential entry and authenticate with the Ayla cloud.

        When called after ``async_step_bluetooth``, the MAC is pre-populated from
        the BLE advertisement. For manually triggered setup flows, the MAC address
        field is included in the form.

        After authentication, lists all Prestige grills in the account. If one
        grill is found it is selected automatically; if multiple are found the
        flow moves to ``async_step_pick_device``.

        Args:
            user_input: Form data submitted by the user, or None to show the form.

        Returns:
            A form result, a pick-device step, or a create-entry result on success.

        """
        errors: dict[str, str] = {}
        schema = _CREDENTIALS_SCHEMA if self._mac else _USER_SCHEMA_WITH_MAC

        if user_input is not None:
            mac = self._mac or user_input.get(CONF_MAC, "")
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            region_key = user_input[CONF_REGION]

            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonBBQApiClient(region, session)
                devices = await client.async_list_devices(username, password)
            except NapoleonBBQApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonBBQApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonBBQApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon BBQ setup")
                errors["base"] = "unknown"
            else:
                if not devices:
                    errors["base"] = "no_devices_found"
                else:
                    self._mac = mac.upper().strip() if mac else mac
                    self._username = username.strip()
                    self._password = password
                    self._region_key = region_key
                    self._devices = devices

                    if len(devices) == 1:
                        dsn, device_name = devices[0]
                        return await self._async_finish(client, dsn, device_name)

                    return await self.async_step_pick_device()

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"name": self._name or ""},
        )

    async def async_step_pick_device(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Let the user choose which Ayla grill to configure when multiple are found.

        Args:
            user_input: Form data with the selected ``CONF_DSN``, or None for form.

        Returns:
            A form result or the create-entry result.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_dsn = user_input[CONF_DSN]
            device_name = next((n for dsn, n in self._devices if dsn == selected_dsn), selected_dsn)
            try:
                region = AYLA_REGIONS[self._region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonBBQApiClient(region, session)
                return await self._async_finish(client, selected_dsn, device_name)
            except NapoleonBBQApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonBBQApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonBBQApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception selecting Napoleon BBQ device")
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

    async def _async_finish(
        self,
        client: NapoleonBBQApiClient,
        dsn: str,
        device_name: str,
    ) -> config_entries.ConfigFlowResult:
        """
        Fetch the local key and create the hub entry (or add to an existing one).

        Looks for an existing hub entry for the authenticated account. If one
        exists, the grill is added as a new sub-entry and the flow aborts with
        "device_added_to_account". Otherwise a new hub entry is created atomically
        with the grill as the first sub-entry.

        Args:
            client: The authenticated Ayla API client.
            dsn: Ayla device serial number of the grill to configure.
            device_name: Display name used as the sub-entry title.

        Returns:
            A create-entry result or an abort result.

        """
        _, local_key = await client.async_get_local_key(self._username, self._password, dsn=dsn)

        mac = self._mac or ""
        mac_lower = mac.lower()
        hub_unique_id = f"{self._username.lower()}_{self._region_key}"
        title = device_name or mac

        # Check whether a hub entry for this account already exists.
        existing_hub = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN) if e.unique_id == hub_unique_id),
            None,
        )

        if existing_hub is not None:
            if any(sub.unique_id == mac_lower for sub in existing_hub.subentries.values()):
                return self.async_abort(reason="already_configured")
            self.hass.config_entries.async_add_subentry(
                existing_hub,
                config_entries.ConfigSubentry(
                    data=MappingProxyType({CONF_MAC: mac, CONF_DSN: dsn, CONF_LOCAL_KEY: local_key}),
                    subentry_type=SUBENTRY_TYPE_DEVICE,
                    title=title,
                    unique_id=mac_lower,
                ),
            )
            return self.async_abort(reason="device_added_to_account")

        await self.async_set_unique_id(hub_unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Napoleon BBQ ({self._username})",
            data={CONF_REGION: self._region_key, CONF_USERNAME: self._username},
            subentries=[
                {
                    "data": {CONF_MAC: mac, CONF_DSN: dsn, CONF_LOCAL_KEY: local_key},
                    "subentry_type": SUBENTRY_TYPE_DEVICE,
                    "title": title,
                    "unique_id": mac_lower,
                }
            ],
        )

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """
        Initiate reauthentication when a local key has been rejected by the grill.

        Args:
            entry_data: The existing hub config entry data (unused; entry accessed
                via ``_get_reauth_entry()``).

        Returns:
            A config flow result forwarding to the reauth confirmation step.

        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Handle reauthentication credential entry.

        Signs in once and refreshes local keys for ALL sub-entries in the hub,
        then reloads the entry.

        Args:
            user_input: Form data submitted by the user, or None to show the form.

        Returns:
            A form result or an abort result on success.

        """
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            region_key = user_input[CONF_REGION]

            device_subentries = [
                sub for sub in reauth_entry.subentries.values() if sub.subentry_type == SUBENTRY_TYPE_DEVICE
            ]
            dsns = [sub.data[CONF_DSN] for sub in device_subentries]

            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonBBQApiClient(region, session)
                local_keys = await client.async_refresh_local_keys(username, password, dsns)
            except NapoleonBBQApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonBBQApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonBBQApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon BBQ reauth")
                errors["base"] = "unknown"
            else:
                for subentry, local_key in zip(device_subentries, local_keys, strict=True):
                    self.hass.config_entries.async_update_subentry(
                        reauth_entry,
                        subentry,
                        data={**subentry.data, CONF_LOCAL_KEY: local_key},
                    )
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_REGION: region_key, CONF_USERNAME: username},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                _CREDENTIALS_SCHEMA,
                {
                    CONF_USERNAME: reauth_entry.data.get(CONF_USERNAME, ""),
                    CONF_REGION: reauth_entry.data.get(CONF_REGION, AYLA_DEFAULT_REGION),
                },
            ),
            errors=errors,
            description_placeholders={"name": reauth_entry.title},
        )
