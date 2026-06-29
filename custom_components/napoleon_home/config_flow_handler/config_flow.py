"""
Config flow for napoleon_home.

This module implements the configuration flow for initial hub setup via BLE
discovery or manual entry, plus reauthentication when local keys need refreshing.

The integration uses a hub model: one config entry per Napoleon account, with
one sub-entry per Napoleon Prestige grill. Each sub-entry stores the grill's
BLE MAC address, Ayla DSN, BLE local key, and key ID.

Setup flow (BLE discovery — primary path):
    1. ``async_step_bluetooth``: Grill advertisement fires. MAC checked against
       existing sub-entries; aborts if already configured. If an account hub
       entry already exists the flow tries to add the grill silently via stored
       Ayla tokens (``_async_try_silent_add``). On success, the user is shown a
       confirm screen with no credential entry required.
    2. ``async_step_user``: User enters Napoleon account credentials and region.
    3. Ayla cloud auth → list all Prestige grills in the account.
    4. If one grill: auto-selected. If multiple: ``async_step_pick_device``.
    5. Local key fetched for the selected DSN. Key validated via BLE auth.
    6. Hub entry created; grill added as the first sub-entry.

Setup flow (manual — fallback when grill is not advertising):
    1. ``async_step_user``: User enters credentials and region.
    2. Ayla cloud device metadata is used to resolve the grill MAC when available.
    3. If no MAC can be resolved, the flow asks the user to start from Bluetooth
       discovery so the grill can be matched reliably.

Reauth flow:
    - Triggered when a coordinator raises ``ConfigEntryAuthFailed`` (e.g. on
      ``s:4`` BLE rejection or revoked refresh token).
    - User re-enters credentials; local keys refreshed for ALL sub-entries in
      a single sign-in round-trip.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeVar

import voluptuous as vol

from custom_components.napoleon_home.api import (
    NapoleonHomeApiClient,
    NapoleonHomeApiClientAuthenticationError,
    NapoleonHomeApiClientCommunicationError,
    NapoleonHomeApiClientError,
)
from custom_components.napoleon_home.bluetooth import NapoleonHomeBLESession
from custom_components.napoleon_home.config_flow_handler.validate import NapoleonHomeNotProvisionedError
from custom_components.napoleon_home.const import (
    AYLA_DEFAULT_REGION,
    AYLA_REGION_EU,
    AYLA_REGION_US,
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
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
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

if TYPE_CHECKING:
    from custom_components.napoleon_home.config_flow_handler.options_flow import NapoleonHomeOptionsFlow
    from custom_components.napoleon_home.config_flow_handler.subentry_flow import NapoleonHomeGrillSubentryFlowHandler

_T = TypeVar("_T")

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


class NapoleonHomeMacAddressRequiredError(HomeAssistantError):
    """Raised when the flow cannot resolve a grill BLE MAC address."""


def _mac_variant_candidates(mac: str) -> list[str]:
    """Return ordered MAC candidates including small last-byte offset variants."""
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        normalised = value.strip().upper()
        if not normalised or normalised in seen:
            return
        seen.add(normalised)
        candidates.append(normalised)

    _add(mac)

    parts = mac.strip().upper().split(":")
    if len(parts) != 6:
        return candidates

    try:
        values = [int(part, 16) for part in parts]
    except ValueError:
        return candidates

    # Ayla metadata can report a sibling interface MAC (for example Wi-Fi)
    # that differs by a small last-byte offset from BLE.
    original = values[5]
    for delta in (1, 2, 3, -1, -2, -3):
        values[5] = (original + delta) % 256
        _add(":".join(f"{value:02X}" for value in values))

    return candidates


async def _async_call_with_token_refresh(
    hass: Any,
    hub_entry: config_entries.ConfigEntry,
    client: NapoleonHomeApiClient,
    api_fn: Callable[[str], Awaitable[_T]],
) -> _T:
    """
    Call ``api_fn(access_token)``, refreshing the Ayla token on 401 if possible.

    On success, updates the hub entry with any fresh tokens obtained during a
    refresh. Raises ``ConfigEntryAuthFailed`` if the refresh token is also
    rejected or unavailable.

    Args:
        hass: The Home Assistant instance.
        hub_entry: The hub config entry holding the stored tokens.
        client: An ``NapoleonHomeApiClient`` instance for making API calls.
        api_fn: Async callable that accepts an access token and returns a result.

    Returns:
        The result of ``api_fn``.

    Raises:
        ConfigEntryAuthFailed: If both the access and refresh tokens are invalid.
        NapoleonHomeApiClientCommunicationError: On network errors.

    """
    token: str = hub_entry.data.get(CONF_ACCESS_TOKEN, "")
    try:
        return await api_fn(token)
    except NapoleonHomeApiClientAuthenticationError:
        refresh: str = hub_entry.data.get(CONF_REFRESH_TOKEN, "")
        if not refresh:
            msg = "Ayla access token expired and no refresh token stored"
            raise ConfigEntryAuthFailed(msg) from None
        try:
            new_access, new_refresh, new_expiry = await client.async_refresh_token(refresh)
        except NapoleonHomeApiClientAuthenticationError as err:
            msg = "Ayla refresh token revoked"
            raise ConfigEntryAuthFailed(msg) from err
        hass.config_entries.async_update_entry(
            hub_entry,
            data={
                **hub_entry.data,
                CONF_ACCESS_TOKEN: new_access,
                CONF_REFRESH_TOKEN: new_refresh,
                CONF_TOKEN_EXPIRY: new_expiry,
            },
        )
        return await api_fn(new_access)


class NapoleonHomeConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for napoleon_home.

    Creates a hub config entry (one per Napoleon account) with the first
    Napoleon Prestige grill as a sub-entry. Additional grills can be added
    via BLE discovery (silently, using stored tokens) or through the sub-entry
    flow. Supports reauthentication for refreshing expired credentials.

    Attributes:
        VERSION: Config entry schema major version.
        MINOR_VERSION: Config entry schema minor version.

    """

    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[NapoleonHomeGrillSubentryFlowHandler]]:
        """
        Return the sub-entry types supported by this integration.

        Args:
            config_entry: The existing hub config entry.

        Returns:
            A dict mapping ``SUBENTRY_TYPE_DEVICE`` to the grill sub-entry flow handler.

        """
        from custom_components.napoleon_home.config_flow_handler.subentry_flow import (  # noqa: PLC0415
            NapoleonHomeGrillSubentryFlowHandler,
        )

        return {SUBENTRY_TYPE_DEVICE: NapoleonHomeGrillSubentryFlowHandler}

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NapoleonHomeOptionsFlow:
        """
        Get the options flow for modifying integration settings.

        Args:
            config_entry: The existing config entry for this integration instance.

        Returns:
            The options flow instance.

        """
        from custom_components.napoleon_home.config_flow_handler.options_flow import (  # noqa: PLC0415
            NapoleonHomeOptionsFlow,
        )

        return NapoleonHomeOptionsFlow()

    def __init__(self) -> None:
        """Initialise the config flow with no pre-discovered device state."""
        self._mac: str | None = None
        self._name: str | None = None
        self._devices: list[tuple[str, str, str]] = []  # [(dsn, display_name, mac)]
        self._username: str = ""
        self._password: str = ""
        self._region_key: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0.0
        # Used by silent-add path (_async_try_silent_add → async_step_auto_add_confirm)
        self._silent_add_hub: config_entries.ConfigEntry | None = None
        self._silent_add_dsn: str = ""
        self._silent_add_local_key: str = ""
        self._silent_add_local_key_id: int = 0
        # Used when grill is unprovisioned: stored so provision_guide can re-attempt finish
        self._pending_dsn: str = ""
        self._pending_device_name: str = ""

    async def async_step_bluetooth(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> config_entries.ConfigFlowResult:
        """
        Handle BLE advertisement discovery of a Napoleon Prestige grill.

        Checks whether the discovered MAC is already configured as a sub-entry.
        If an account hub entry already exists, attempts to add the grill silently
        using stored Ayla tokens — no user credentials required. Falls through to
        the credential entry step if no hub exists or the silent add cannot proceed.

        Args:
            discovery_info: BLE advertisement data from the HA Bluetooth integration.

        Returns:
            A config flow result: auto-add confirm, user credentials form, or abort.

        """
        LOGGER.info(
            "Napoleon Home: setup_stage=bluetooth_step_enter address=%s name=%s",
            discovery_info.address,
            discovery_info.name,
        )
        mac_lower = discovery_info.address.lower()
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for sub in entry.subentries.values():
                if sub.unique_id == mac_lower:
                    LOGGER.info(
                        "Napoleon Home: setup_stage=bluetooth_step_abort reason=already_configured address=%s",
                        discovery_info.address,
                    )
                    return self.async_abort(reason="already_configured")

        self._mac = discovery_info.address
        self._name = discovery_info.name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}

        # If account hub entries already exist, try to add silently against each.
        result = await self._async_try_silent_add_any_hub(discovery_info.address)
        if result is not None:
            LOGGER.info(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=silent_add address=%s",
                discovery_info.address,
            )
            return result

        LOGGER.info(
            "Napoleon Home: setup_stage=bluetooth_step_branch branch=user_credentials address=%s",
            discovery_info.address,
        )
        return await self.async_step_user()

    async def async_step_factory_reset_guide(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Guide the user through factory-resetting a grill bonded to another device.

        Shown when the grill rejects BLE writes with ATT error 0x05 (Insufficient
        Authentication). A provisioned Napoleon grill disables new BLE bonding after
        initial setup; the only way to re-enable bonding is a factory reset, after
        which the grill must be provisioned again via the Napoleon app.

        After reset the grill returns to the unprovisioned state, so on confirmation
        the flow continues to ``async_step_provision_guide``.

        Args:
            user_input: Empty dict on confirmation, or None to show the form.

        Returns:
            A form result or the provision guide step.

        """
        if user_input is not None:
            return await self.async_step_provision_guide()

        return self.async_show_form(
            step_id="factory_reset_guide",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def async_step_provision_guide(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Guide the user through provisioning an unregistered grill.

        Shown when the grill responds with ``s:6`` on the BLE provisioning probe,
        meaning it has not been set up via the Napoleon app yet.

        Two confirmation paths:

        - **Credentials path** (``_pending_dsn`` set): user already signed in;
          re-runs ``_async_finish`` for the pending DSN. Shows an error if the
          grill is still not provisioned.
        - **BLE discovery path** (``_pending_dsn`` empty): credentials not yet
          collected; attempts a silent add via stored account tokens, then falls
          back to credential entry.

        Args:
            user_input: Empty dict on confirmation, or None to show the form.

        Returns:
            A form result, a create-entry result, an auto-add confirm, or the
            user credentials form.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            if self._pending_dsn:
                # Credentials path: re-run _async_finish for the same DSN.
                # The provisioning probe will determine if now provisioned.
                region = AYLA_REGIONS[self._region_key]
                client = NapoleonHomeApiClient(region, async_get_clientsession(self.hass))
                try:
                    return await self._async_finish(client, self._pending_dsn, self._pending_device_name)
                except NapoleonHomeNotProvisionedError:
                    errors["base"] = "ble_not_provisioned"
                except NapoleonHomeMacAddressRequiredError:
                    errors["base"] = "ble_discovery_required"
                except ConfigEntryAuthFailed:
                    errors["base"] = "invalid_auth"
                except HomeAssistantError:
                    errors["base"] = "cannot_connect"
                except Exception:  # noqa: BLE001
                    LOGGER.exception("Unexpected exception re-attempting Napoleon Home setup after provisioning")
                    errors["base"] = "unknown"
            else:
                # BLE discovery path: credentials not yet collected.
                result = await self._async_try_silent_add_any_hub(self._mac or "")
                if result is not None:
                    return result
                return await self.async_step_user()

        return self.async_show_form(
            step_id="provision_guide",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def _async_try_silent_add_any_hub(
        self,
        mac: str,
    ) -> config_entries.ConfigFlowResult | None:
        """Try silent-add against all existing hub entries until one succeeds."""
        if not mac:
            return None
        for hub_entry in self.hass.config_entries.async_entries(DOMAIN):
            result = await self._async_try_silent_add(hub_entry, mac)
            if result is not None:
                return result
        return None

    async def _async_try_silent_add(
        self,
        hub_entry: config_entries.ConfigEntry,
        mac: str,
    ) -> config_entries.ConfigFlowResult | None:
        """
        Attempt to add a newly discovered grill using stored Ayla tokens.

        Uses the hub entry's stored access token (refreshing silently if expired)
        to look up the grill by MAC in ``devices.json`` and fetch its local key
        from ``connection_config.json``. On success returns an auto-add confirm
        step; returns ``None`` on any failure so the caller can fall back to the
        credential entry step.

        Args:
            hub_entry: The existing account hub config entry.
            mac: BLE MAC address of the newly discovered grill.

        Returns:
            A flow result for ``async_step_auto_add_confirm``, or ``None``.

        """
        if not mac:
            return None

        region_key: str = hub_entry.data.get(CONF_REGION, "")
        region = AYLA_REGIONS.get(region_key)
        if region is None:
            return None

        client = NapoleonHomeApiClient(region, async_get_clientsession(self.hass))
        mac_candidates = _mac_variant_candidates(mac)
        try:
            result = await _async_call_with_token_refresh(
                self.hass,
                hub_entry,
                client,
                lambda token: client.async_fetch_device_by_possible_macs(token, mac_candidates),
            )
        except ConfigEntryAuthFailed, NapoleonHomeApiClientError:
            return None

        if result is None:
            return None  # MAC not found in account

        dsn, name, local_key, local_key_id = result

        # DSN uniqueness check
        if any(
            sub.data.get(CONF_DSN) == dsn
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            for sub in entry.subentries.values()
        ):
            return self.async_abort(reason="already_configured")

        self._name = name or mac
        self.context["title_placeholders"] = {"name": self._name}
        self._silent_add_hub = hub_entry
        self._silent_add_dsn = dsn
        self._silent_add_local_key = local_key
        self._silent_add_local_key_id = local_key_id
        return await self.async_step_auto_add_confirm()

    async def async_step_auto_add_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Ask the user to confirm adding a newly discovered grill.

        Shown when a new grill is found via BLE and added silently using stored
        account credentials. No password entry is required. On confirmation,
        validates the BLE key and adds the grill as a sub-entry.

        Args:
            user_input: Empty dict on confirmation, or None to show the form.

        Returns:
            A form result or an abort result on success.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            mac = self._mac or ""
            if not mac:
                LOGGER.warning("Napoleon Home: setup_stage=silent_add_confirm_failed reason=missing_mac")
                errors["base"] = "cannot_connect"

            if not errors:
                hub_entry = self._silent_add_hub
                assert hub_entry is not None
                mac_lower = mac.lower()
                title = self._name or mac
                LOGGER.info(
                    "Napoleon Home: setup_stage=silent_add_confirmed hub_entry_id=%s dsn=%s mac=%s",
                    hub_entry.entry_id,
                    self._silent_add_dsn,
                    mac,
                )

                if any(sub.unique_id == mac_lower for sub in hub_entry.subentries.values()):
                    return self.async_abort(reason="already_configured")

                self.hass.config_entries.async_add_subentry(
                    hub_entry,
                    config_entries.ConfigSubentry(
                        data=MappingProxyType(
                            {
                                CONF_MAC: mac,
                                CONF_DSN: self._silent_add_dsn,
                                CONF_LOCAL_KEY: self._silent_add_local_key,
                                CONF_LOCAL_KEY_ID: self._silent_add_local_key_id,
                            }
                        ),
                        subentry_type=SUBENTRY_TYPE_DEVICE,
                        title=title,
                        unique_id=mac_lower,
                    ),
                )
                LOGGER.info(
                    "Napoleon Home: silently added grill %s (%s) to existing account entry",
                    title,
                    mac,
                )
                return self.async_abort(reason="device_added_to_account")

        return self.async_show_form(
            step_id="auto_add_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Handle credential entry and authenticate with the Ayla cloud.

        When called after ``async_step_bluetooth``, the MAC is pre-populated from
        the BLE advertisement. For manually triggered setup flows, the flow uses
        the Ayla device metadata to resolve the MAC address automatically.

        After authentication, lists all Prestige grills in the account. If one
        grill is found it is selected automatically; if multiple are found the
        flow moves to ``async_step_pick_device``.

        Args:
            user_input: Form data submitted by the user, or None to show the form.

        Returns:
            A form result, a pick-device step, or a create-entry result on success.

        """
        errors: dict[str, str] = {}
        schema = _CREDENTIALS_SCHEMA

        if user_input is not None:
            mac = self._mac or ""
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            region_key = user_input[CONF_REGION]

            try:
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, session)
                devices, access_token, refresh_token, token_expiry = await client.async_list_devices(username, password)
            except NapoleonHomeApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonHomeApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonHomeApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon Home setup")
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
                    self._access_token = access_token
                    self._refresh_token = refresh_token
                    self._token_expiry = token_expiry

                    if len(devices) == 1:
                        dsn, device_name, api_mac = devices[0]
                        if not self._mac and api_mac:
                            self._mac = api_mac
                        try:
                            return await self._async_finish(client, dsn, device_name)
                        except NapoleonHomeNotProvisionedError:
                            self._pending_dsn = dsn
                            self._pending_device_name = device_name
                            return await self.async_step_provision_guide()
                        except NapoleonHomeMacAddressRequiredError:
                            errors["base"] = "ble_discovery_required"
                        except ConfigEntryAuthFailed:
                            errors["base"] = "invalid_auth"
                        except HomeAssistantError:
                            errors["base"] = "cannot_connect"
                    else:
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
            device_name = next((n for dsn, n, _mac in self._devices if dsn == selected_dsn), selected_dsn)
            api_mac = next((_mac for dsn, _n, _mac in self._devices if dsn == selected_dsn), "")
            if not self._mac and api_mac:
                self._mac = api_mac
            try:
                region = AYLA_REGIONS[self._region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, session)
                return await self._async_finish(client, selected_dsn, device_name)
            except NapoleonHomeNotProvisionedError:
                self._pending_dsn = selected_dsn
                self._pending_device_name = device_name
                return await self.async_step_provision_guide()
            except NapoleonHomeApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonHomeApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonHomeApiClientError:
                errors["base"] = "unknown"
            except NapoleonHomeMacAddressRequiredError:
                errors["base"] = "ble_discovery_required"
            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except HomeAssistantError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception selecting Napoleon Home device")
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

    async def _async_finish(
        self,
        client: NapoleonHomeApiClient,
        dsn: str,
        device_name: str,
    ) -> config_entries.ConfigFlowResult:
        """
        Fetch the local key, validate it via BLE, and create or update the hub entry.

        Uses the access token already stored on ``self._access_token`` from the
        prior ``async_list_devices`` call to avoid a redundant sign-in. Performs
        a DSN uniqueness check before creating the config entry. If a BLE MAC is
        known the local key is validated by completing a BLE auth handshake.

        Args:
            client: The Ayla API client instance (used to fetch the local key).
            dsn: Ayla device serial number of the grill to configure.
            device_name: Display name used as the sub-entry title.

        Returns:
            A create-entry result or an abort result.

        Raises:
            ConfigEntryAuthFailed: If BLE key validation is rejected (s:4).
            HomeAssistantError: If BLE key validation times out or grill is unreachable.
            NapoleonHomeApiClientError: If the local key cannot be fetched from Ayla.

        """
        # DSN uniqueness check
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for sub in entry.subentries.values():
                if sub.data.get(CONF_DSN) == dsn:
                    return self.async_abort(reason="already_configured")

        # Use stored token to avoid double sign-in; fall back to credentials if needed
        if self._access_token:
            local_key, local_key_id = await client.async_fetch_key(self._access_token, dsn)
        else:
            (
                _,
                local_key,
                local_key_id,
                self._access_token,
                self._refresh_token,
                self._token_expiry,
            ) = await client.async_get_local_key(self._username, self._password, dsn=dsn)

        # Validate the key via BLE and recover from stale Ayla MACs by trying
        # currently discoverable Napoleon/Prestige advertisements.
        api_mac = next((_mac for _dsn, _name, _mac in self._devices if _dsn == dsn), "")
        resolved_mac = await self._async_resolve_valid_mac(
            selected_mac=self._mac or api_mac,
            device_name=device_name,
            local_key=local_key,
            expected_dsn=dsn,
        )
        self._mac = resolved_mac
        mac = resolved_mac

        mac_lower = mac.lower()
        hub_unique_id = f"{self._username.lower()}_{self._region_key}"
        LOGGER.info(
            "Napoleon Home: setup_stage=finish path=full_setup dsn=%s selected_mac=%s api_mac=%s hub_unique_id=%s",
            dsn,
            mac,
            api_mac,
            hub_unique_id,
        )
        title = device_name or mac
        hub_data = {
            CONF_REGION: self._region_key,
            CONF_USERNAME: self._username,
            CONF_ACCESS_TOKEN: self._access_token,
            CONF_REFRESH_TOKEN: self._refresh_token,
            CONF_TOKEN_EXPIRY: self._token_expiry,
        }
        subentry_data = {CONF_MAC: mac, CONF_DSN: dsn, CONF_LOCAL_KEY: local_key, CONF_LOCAL_KEY_ID: local_key_id}

        # Check whether a hub entry for this account already exists.
        existing_hub = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN) if e.unique_id == hub_unique_id),
            None,
        )

        if existing_hub is not None:
            if any(sub.unique_id == mac_lower for sub in existing_hub.subentries.values()):
                return self.async_abort(reason="already_configured")
            self.hass.config_entries.async_update_entry(existing_hub, data={**existing_hub.data, **hub_data})
            self.hass.config_entries.async_add_subentry(
                existing_hub,
                config_entries.ConfigSubentry(
                    data=MappingProxyType(subentry_data),
                    subentry_type=SUBENTRY_TYPE_DEVICE,
                    title=title,
                    unique_id=mac_lower,
                ),
            )
            return self.async_abort(reason="device_added_to_account")

        await self.async_set_unique_id(hub_unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Napoleon Home ({self._username})",
            data=hub_data,
            subentries=[
                {
                    "data": subentry_data,
                    "subentry_type": SUBENTRY_TYPE_DEVICE,
                    "title": title,
                    "unique_id": mac_lower,
                }
            ],
        )

    async def _async_resolve_valid_mac(
        self,
        selected_mac: str,
        device_name: str,
        local_key: str,
        expected_dsn: str = "",
    ) -> str:
        """Resolve and validate a working BLE MAC for the selected grill."""
        candidates: list[str] = []
        seen: set[str] = set()

        def _add_candidate(mac: str) -> None:
            normalised = mac.strip().upper()
            if not normalised or normalised in seen:
                return
            seen.add(normalised)
            candidates.append(normalised)

        for candidate in _mac_variant_candidates(selected_mac):
            _add_candidate(candidate)

        target_name = (device_name or "").strip().casefold()
        prestige_like_candidates: list[str] = []
        for service_info in async_discovered_service_info(self.hass, connectable=True):
            address = service_info.address.upper()
            name = (service_info.name or "").strip()
            if not name:
                continue
            folded = name.casefold()
            if target_name and folded == target_name:
                _add_candidate(address)
                continue
            if "napoleon" in folded or "prestige" in folded:
                prestige_like_candidates.append(address)

        for mac in prestige_like_candidates:
            _add_candidate(mac)

        if not candidates:
            msg = "No BLE MAC address available for selected grill; start setup from Bluetooth discovery"
            raise NapoleonHomeMacAddressRequiredError(msg)

        for mac in candidates:
            ble_device = async_ble_device_from_address(self.hass, mac, connectable=True)
            if ble_device is None:
                continue
            if selected_mac and mac != selected_mac.upper():
                LOGGER.info(
                    "Napoleon Home: setup_stage=mac_fallback original=%s resolved=%s device=%s",
                    selected_mac,
                    mac,
                    device_name,
                )
            # Probe provisioning status. Returns False (s:6), True (challenge), or
            # None (inconclusive — BLE busy/unreachable; don't block setup).
            provisioned: bool | None = None
            try:
                async with NapoleonHomeBLESession(mac) as session:
                    await session.connect(ble_device)
                    provisioned = await session.check_provisioned()
            except Exception:  # noqa: BLE001
                LOGGER.debug(
                    "Napoleon Home %s: provisioning probe failed — proceeding without check",
                    mac,
                )
            if provisioned is False:
                msg = f"Napoleon Home {mac}: grill not provisioned (s:6)"
                raise NapoleonHomeNotProvisionedError(msg)
            return mac

        msg = "Resolved BLE MAC is not currently discoverable; start setup from Bluetooth discovery"
        raise NapoleonHomeMacAddressRequiredError(msg)

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> config_entries.ConfigFlowResult:
        """
        Initiate reauthentication when credentials need refreshing.

        Args:
            entry_data: The existing hub config entry data (unused).

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
        then reloads the entry. Triggered by a ``s:4`` BLE rejection (rotated key)
        or a revoked Ayla refresh token.

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
                client = NapoleonHomeApiClient(region, session)
                keys, access_token, refresh_token, token_expiry = await client.async_refresh_local_keys(
                    username, password, dsns
                )
            except NapoleonHomeApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except NapoleonHomeApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except NapoleonHomeApiClientError:
                errors["base"] = "unknown"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception during Napoleon Home reauth")
                errors["base"] = "unknown"
            else:
                for subentry, (local_key, local_key_id) in zip(device_subentries, keys, strict=True):
                    self.hass.config_entries.async_update_subentry(
                        reauth_entry,
                        subentry,
                        data={**subentry.data, CONF_LOCAL_KEY: local_key, CONF_LOCAL_KEY_ID: local_key_id},
                    )
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_REGION: region_key,
                        CONF_USERNAME: username,
                        CONF_ACCESS_TOKEN: access_token,
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_TOKEN_EXPIRY: token_expiry,
                    },
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
