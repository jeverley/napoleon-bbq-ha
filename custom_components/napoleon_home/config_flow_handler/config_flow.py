"""
Config flow for napoleon_home.

This module implements the configuration flow for initial hub setup via BLE
discovery, plus reauthentication when local keys need refreshing.

The integration uses a hub model: one config entry per Napoleon account, with
one sub-entry per Napoleon Prestige grill. Each sub-entry stores the grill's
BLE MAC address, Ayla DSN, BLE local key, and key ID.

Setup flow (BLE discovery — only supported path):
    1. ``async_step_bluetooth``: Grill advertisement fires. MAC checked against
       existing sub-entries; aborts if already configured. Probes provisioning
       state via BLE (DSN read from open GATT characteristic in the same session):
         - s:6 (not provisioned) → ``async_step_provision_guide``
         - ATT 0x05 (bonded to another device) → ``async_step_factory_reset_guide``
         - challenge or inconclusive → ``async_step_key_retrieval``
    2. ``async_step_provision_guide``: User provisions the grill in the Napoleon
       app. On confirm, re-probes; routes to ``async_step_key_retrieval`` when
       provisioned, or shows an error if still s:6.
    3. ``async_step_factory_reset_guide``: User factory-resets the grill. On
       confirm, re-probes; routes to ``async_step_provision_guide`` when s:6,
       or shows an error if ATT 0x05 persists.
    4. ``async_step_key_retrieval``: User enters Napoleon account credentials.
       Device matched by DSN (from GATT read) or fuzzy MAC offset. Local key
       fetched via API, validated by BLE auth, hub entry and sub-entry created.

Manual setup (``async_step_user``) is not supported — aborts with
``discovery_required``. The grill must be discovered via BLE advertisement.

Reauth flow:
    - Triggered when a coordinator raises ``ConfigEntryAuthFailed`` (e.g. on
      ``s:4`` BLE rejection or revoked refresh token).
    - User re-enters credentials; local keys refreshed for ALL sub-entries in
      a single sign-in round-trip.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from custom_components.napoleon_home.api import (
    NapoleonHomeApiClient,
    NapoleonHomeApiClientAuthenticationError,
    NapoleonHomeApiClientCommunicationError,
    NapoleonHomeApiClientError,
)
from custom_components.napoleon_home.bluetooth import (
    NapoleonHomeAlreadyBondedError,
    NapoleonHomeBLESession,
    NapoleonHomeNotProvisionedError,
)
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


class NapoleonHomeConfigFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Handle a config flow for napoleon_home.

    Creates a hub config entry (one per Napoleon account) with the first
    Napoleon Prestige grill as a sub-entry. Additional grills can be added
    via the sub-entry flow. Supports reauthentication for refreshing expired
    credentials.

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
        self._ble_dsn: str | None = None
        self._username: str = ""
        self._password: str = ""
        self._region_key: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
        self._token_expiry: float = 0.0

    async def async_step_bluetooth(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ) -> config_entries.ConfigFlowResult:
        """
        Handle BLE advertisement discovery of a Napoleon Prestige grill.

        Probes provisioning state via BLE (DSN read from open GATT characteristic
        during the same connection). Routes to the appropriate setup step:
          - s:6 (not provisioned) → provision_guide
          - ATT 0x05 (bonded to another device) → factory_reset_guide
          - challenge or inconclusive → key_retrieval (credentials form)

        Args:
            discovery_info: BLE advertisement data from the HA Bluetooth integration.

        Returns:
            A config flow result: a guide step or credentials form.

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

        # BLE probe: pair + check_provisioned — determines setup path.
        # DSN is read from the open GATT characteristic during the same connection.
        try:
            provisioned = await self._async_probe_ble(discovery_info.address)
        except NapoleonHomeAlreadyBondedError:
            LOGGER.info(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=factory_reset address=%s",
                discovery_info.address,
            )
            return await self.async_step_factory_reset_guide()

        if provisioned is False:
            LOGGER.info(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=provision_guide address=%s",
                discovery_info.address,
            )
            return await self.async_step_provision_guide()

        LOGGER.info(
            "Napoleon Home: setup_stage=bluetooth_step_branch branch=key_retrieval address=%s provisioned=%s",
            discovery_info.address,
            provisioned,
        )
        return await self.async_step_key_retrieval()

    async def async_step_factory_reset_guide(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Guide the user through factory-resetting a grill bonded to another device.

        Shown when the grill rejects BLE writes with ATT error 0x05 (Insufficient
        Authentication). The only way to re-enable bonding is a factory reset (hold
        ignition button 10 s until the grill beeps). After reset the grill returns
        to the unprovisioned state (s:6), so confirmation re-probes and routes to
        provision_guide. If ATT 0x05 persists, the reset has not been detected yet.

        Args:
            user_input: Empty dict on confirmation, or None to show the form.

        Returns:
            A form result, the provision guide step, or the key retrieval step.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                provisioned = await self._async_probe_ble(self._mac or "")
            except NapoleonHomeAlreadyBondedError:
                errors["base"] = "reset_not_detected"
            else:
                if provisioned is True:
                    return await self.async_step_key_retrieval()
                if provisioned is False:
                    # Reset confirmed: grill is unprovisioned — proceed to provision guide.
                    return await self.async_step_provision_guide()
                # None — inconclusive; grill did not respond.
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="factory_reset_guide",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def async_step_provision_guide(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Guide the user through provisioning an unregistered grill via the Napoleon app.

        Shown when the grill responds with ``s:6`` on the BLE provisioning probe,
        meaning it has not been set up via the Napoleon app yet. The user is asked to
        open the Napoleon app, create an account, and provision the grill, then confirm.

        On confirmation, re-probes the grill:
          - challenge (provisioned) → key_retrieval
          - still s:6              → error "ble_not_provisioned" (stay on form)
          - ATT 0x05               → factory_reset_guide (grill bonded to another device)
          - None (unreachable)     → error "cannot_connect"

        Args:
            user_input: Empty dict on confirmation, or None to show the form.

        Returns:
            A form result, the factory reset guide, or the key retrieval step.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                provisioned = await self._async_probe_ble(self._mac or "")
            except NapoleonHomeAlreadyBondedError:
                return await self.async_step_factory_reset_guide()
            else:
                if provisioned is True:
                    return await self.async_step_key_retrieval()
                if provisioned is False:
                    errors["base"] = "ble_not_provisioned"
                else:
                    errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="provision_guide",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def _async_probe_ble(self, mac: str) -> bool | None:
        """Connect, bond, and probe provisioning state.

        Returns True (challenge received), False (s:6 — not provisioned), or None
        (grill not discoverable or probe inconclusive).

        On first call (``self._ble_dsn is None``) also reads the DSN from the open
        GATT DUID characteristic during the same connection.

        Raises:
            NapoleonHomeAlreadyBondedError: Grill refuses writes with ATT 0x05.

        """
        ble_device = async_ble_device_from_address(self.hass, mac, connectable=True)
        if ble_device is None:
            return None
        try:
            async with NapoleonHomeBLESession(mac) as session:
                await session.connect(ble_device)
                if self._ble_dsn is None:
                    self._ble_dsn = await session.read_dsn()
                return await session.check_provisioned()
        except NapoleonHomeAlreadyBondedError:
            raise
        except Exception:  # noqa: BLE001
            LOGGER.debug("Napoleon Home %s: BLE probe failed — treating as inconclusive", mac)
            return None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Abort manual setup — this integration is BLE-discovery only."""
        return self.async_abort(reason="discovery_required")

    async def async_step_key_retrieval(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Collect Napoleon account credentials and retrieve the grill's local key.

        Reached after the BLE probe confirms the grill is provisioned (or gives an
        inconclusive result). Lists devices in the account and matches the grill by
        DSN (from the pre/post-bond GATT read) or fuzzy MAC offset variants as
        fallback. Fetches the local key and calls ``_async_finish`` to validate via
        BLE and create the config entry.

        Args:
            user_input: Form data submitted by the user, or None to show the form.

        Returns:
            A form result or a create-entry/abort result on success.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
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
                LOGGER.exception("Unexpected exception during Napoleon Home key retrieval")
                errors["base"] = "unknown"
            else:
                # Match device: prefer DSN from GATT read, fall back to fuzzy MAC.
                mac_variants = set(_mac_variant_candidates(self._mac or ""))
                match: tuple[str, str, str] | None = None
                if self._ble_dsn:
                    match = next((d for d in devices if d[0] == self._ble_dsn), None)
                    if match is None:
                        LOGGER.warning(
                            "Napoleon Home: DSN %s not found in account — falling back to MAC match",
                            self._ble_dsn,
                        )
                if match is None:
                    match = next((d for d in devices if d[2].upper() in mac_variants), None)

                if match is None:
                    errors["base"] = "no_devices_found"
                else:
                    dsn, device_name, _ = match
                    self._username = username.strip()
                    self._password = password
                    self._region_key = region_key
                    self._access_token = access_token
                    self._refresh_token = refresh_token
                    self._token_expiry = token_expiry
                    try:
                        local_key, local_key_id = await client.async_fetch_key(access_token, dsn)
                        return await self._async_finish(dsn, device_name, local_key, local_key_id)
                    except NapoleonHomeNotProvisionedError:
                        return await self.async_step_provision_guide()
                    except NapoleonHomeMacAddressRequiredError:
                        errors["base"] = "ble_discovery_required"
                    except ConfigEntryAuthFailed:
                        errors["base"] = "ble_key_rejected"
                    except HomeAssistantError:
                        errors["base"] = "cannot_connect"
                    except NapoleonHomeApiClientError:
                        errors["base"] = "cannot_connect"
                    except Exception:  # noqa: BLE001
                        LOGGER.exception("Unexpected exception finalising Napoleon Home setup")
                        errors["base"] = "unknown"

        return self.async_show_form(
            step_id="key_retrieval",
            data_schema=self.add_suggested_values_to_schema(
                _CREDENTIALS_SCHEMA,
                {
                    CONF_USERNAME: self._username or "",
                    CONF_REGION: self._region_key or AYLA_DEFAULT_REGION,
                },
            ),
            errors=errors,
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def _async_finish(
        self,
        dsn: str,
        device_name: str,
        local_key: str,
        local_key_id: int,
    ) -> config_entries.ConfigFlowResult:
        """
        Validate the local key via BLE and create or update the hub + sub-entry.

        Resolves connectable MAC candidates (offset variants + discovered services),
        then authenticates with each until one accepts the key. Creates or updates
        the hub config entry and adds the grill as a sub-entry.

        Args:
            dsn: Ayla device serial number of the grill to configure.
            device_name: Display name used as the sub-entry title.
            local_key: Ayla local key for BLE authentication.
            local_key_id: Ayla local key ID stored alongside the key.

        Returns:
            A create-entry result or an abort result.

        Raises:
            ConfigEntryAuthFailed: If BLE key validation is rejected (s:4) on all candidates.
            NapoleonHomeNotProvisionedError: If the grill reports s:6 during auth.
            HomeAssistantError: If the grill is not discoverable for authentication.

        """
        # DSN uniqueness check
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for sub in entry.subentries.values():
                if sub.data.get(CONF_DSN) == dsn:
                    return self.async_abort(reason="already_configured")

        # Resolve connectable MAC candidates (offset variants + name-matched discoveries).
        mac_candidates = await self._async_resolve_valid_mac(device_name)

        # Full BLE authentication — try each candidate until one accepts the key.
        mac: str | None = None
        last_auth_err: ConfigEntryAuthFailed | None = None
        for candidate in mac_candidates:
            ble_device = async_ble_device_from_address(self.hass, candidate, connectable=True)
            if ble_device is None:
                LOGGER.debug("Napoleon Home %s: not discoverable for authentication — skipping", candidate)
                continue
            try:
                async with NapoleonHomeBLESession(candidate) as session:
                    await session.connect(ble_device)
                    await session.authenticate(local_key)
                mac = candidate
                break
            except NapoleonHomeAlreadyBondedError:
                return await self.async_step_factory_reset_guide()
            except NapoleonHomeNotProvisionedError:
                raise
            except ConfigEntryAuthFailed as err:
                LOGGER.debug("Napoleon Home %s: auth rejected (s:4) — trying next candidate", candidate)
                last_auth_err = err
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Napoleon Home %s: BLE auth error — skipping candidate: %s", candidate, err)

        if mac is None:
            if last_auth_err is not None:
                raise last_auth_err
            msg = f"Napoleon Home {mac_candidates[0]}: grill not discoverable for authentication"
            raise HomeAssistantError(msg)

        self._mac = mac
        mac_lower = mac.lower()
        hub_unique_id = f"{self._username.lower()}_{self._region_key}"
        LOGGER.info(
            "Napoleon Home: setup_stage=finish dsn=%s mac=%s hub_unique_id=%s",
            dsn,
            mac,
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

    async def _async_resolve_valid_mac(self, device_name: str) -> list[str]:
        """Return connectable MAC candidates for BLE authentication.

        Builds candidates from offset variants of ``self._mac`` plus any currently
        advertising devices whose name matches ``device_name`` (exact) or looks
        like a Napoleon/Prestige grill (fuzzy fallback). Filters to those currently
        discoverable as connectable. The original MAC is always tried first.

        Raises:
            NapoleonHomeMacAddressRequiredError: No connectable candidates found.

        """
        candidates: list[str] = []
        seen: set[str] = set()

        def _add_candidate(mac: str) -> None:
            normalised = mac.strip().upper()
            if not normalised or normalised in seen:
                return
            seen.add(normalised)
            candidates.append(normalised)

        for candidate in _mac_variant_candidates(self._mac or ""):
            _add_candidate(candidate)

        target_name = (device_name or "").strip().casefold()
        prestige_like: list[str] = []
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
                prestige_like.append(address)

        for mac in prestige_like:
            _add_candidate(mac)

        result = [m for m in candidates if async_ble_device_from_address(self.hass, m, connectable=True) is not None]
        if not result:
            msg = f"Napoleon Home {self._mac}: grill not discoverable — ensure it is powered on"
            raise NapoleonHomeMacAddressRequiredError(msg)
        return result

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
