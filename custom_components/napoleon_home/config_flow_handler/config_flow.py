"""
Config flow for napoleon_home.

This module implements the configuration flow for initial hub setup via BLE
discovery, plus reauthentication when local keys need refreshing.

The integration uses a hub model: one config entry per Napoleon account, with
per-device data stored in ``entry.data[CONF_DEVICES]`` keyed by MAC address.

Setup flow (BLE discovery — only supported path):
    1. ``async_step_bluetooth``: Grill advertisement fires. MAC validated against
       existing entries and Napoleon device name prefixes; aborts if already
       configured or not a Napoleon device. If the grill has no advertisement
       local name, does a lightweight BLE connect to read the 0x2A00 model string
       (no pairing). Shows a confirmation form (``bluetooth_confirm``).
    2. ``async_step_bluetooth_confirm``: User taps Submit. Full BLE probe runs:
       connect → pair → check_provisioned. Routes based on result:
         - s:6 (not provisioned) → ``async_step_provision_guide``
         - ATT 0x05 / pairing rejected (bonded to another device)
           → ``async_step_factory_reset_guide``
         - challenge or inconclusive → ``async_step_key_retrieval``
    3. ``async_step_provision_guide``: User provisions the grill in the Napoleon
       app. On confirm, re-probes; routes to ``async_step_key_retrieval`` when
       provisioned, or shows an error if still s:6.
    4. ``async_step_factory_reset_guide``: User factory-resets the grill. On
       confirm, re-probes; routes to ``async_step_provision_guide`` when s:6,
       or shows an error if ATT 0x05 persists.
    5. ``async_step_key_retrieval``: User enters Napoleon account credentials.
       Device matched by DSN (from GATT read after bonding) when known; otherwise
       every account device's key is tried against the grill via real BLE auth
       until one is accepted. Hub entry and device data created on success.

Manual setup (``async_step_user``) is not supported — aborts with
``discovery_required``. The grill must be discovered via BLE advertisement.

Reauth flow:
    - Triggered when a coordinator raises ``ConfigEntryAuthFailed`` (e.g. on
      ``s:4`` BLE rejection or revoked refresh token).
    - User re-enters credentials; local keys refreshed for ALL devices in
      a single sign-in round-trip.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

import contextlib
import enum
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
    CONF_DEVICES,
    CONF_DSN,
    CONF_LOCAL_KEY,
    CONF_LOCAL_KEY_ID,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRY,
    DOMAIN,
    LOGGER,
    NAPOLEON_NAME_PREFIXES,
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


class NapoleonHomeBLEConnectionError(HomeAssistantError):
    """Raised when BLE authentication fails due to a connection error (e.g. timeout)."""


class ProbeOutcome(enum.Enum):
    """Result of a BLE provisioning probe."""

    PROVISIONED = "provisioned"
    NOT_PROVISIONED = "not_provisioned"  # s:6
    BONDED_TO_OTHER = "bonded_to_other"  # ATT 0x05
    UNREACHABLE = "unreachable"  # device not found or probe inconclusive


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
    Napoleon Prestige grill stored in ``entry.data[CONF_DEVICES]``. Additional
    grills can be added via the options flow. Supports reauthentication for
    refreshing expired credentials.

    Attributes:
        VERSION: Config entry schema major version.
        MINOR_VERSION: Config entry schema minor version.

    """

    VERSION = 3
    MINOR_VERSION = 1

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
        self._ble_display_name: str | None = None
        self._ble_model: str | None = None
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
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if discovery_info.address.upper() in entry.data.get(CONF_DEVICES, {}):
                LOGGER.info(
                    "Napoleon Home: setup_stage=bluetooth_step_abort reason=already_configured address=%s",
                    discovery_info.address,
                )
                return self.async_abort(reason="already_configured")

        # Napoleon grills advertise a local name starting with a known prefix.
        # If a local name is present but doesn't match any known prefix, this is a
        # non-Napoleon Ayla device sharing the FE28 service UUID — fast reject.
        # HA sets discovery_info.name to the address when no local name is present,
        # so treat name == address as "no local name".
        local_name = discovery_info.name if discovery_info.name != discovery_info.address else None
        if local_name and not local_name.startswith(NAPOLEON_NAME_PREFIXES):
            LOGGER.debug(
                "Napoleon Home: setup_stage=bluetooth_step_abort reason=not_napoleon address=%s name=%s",
                discovery_info.address,
                local_name,
            )
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address.upper())

        self._mac = discovery_info.address
        # Use the advertisement name if present; otherwise fall back to the address.
        self._name = local_name or self._name or discovery_info.address
        self.context["title_placeholders"] = {"name": self._name}

        # If the grill hasn't advertised a name and we haven't read one yet (or a
        # previous read failed), do a quick read-only BLE connect to get DSN and
        # display name before showing the confirmation form.
        if not local_name and not self._ble_display_name:
            await self._async_read_ble_metadata(self._mac)
            if self._ble_model and not self._ble_model.startswith(NAPOLEON_NAME_PREFIXES):
                return self.async_abort(reason="not_supported")
            if self._ble_display_name:
                self._name = self._ble_display_name
                self.context["title_placeholders"] = {"name": self._name}

        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Show confirmation form; on submit probe and route to the correct setup step."""
        if user_input is not None:
            return await self._async_probe_and_route()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._name or self._mac or ""},
        )

    async def _async_read_ble_metadata(self, mac: str) -> None:
        """Best-effort read of model name (0x2A00) from open GATT characteristics.

        Connects without pairing or subscribing. All failures are suppressed —
        callers fall back to the MAC address as the device name.

        """
        ble_device = async_ble_device_from_address(self.hass, mac, connectable=True)
        if ble_device is None:
            return
        try:
            async with NapoleonHomeBLESession(mac) as session:
                await session.read_open_characteristics(ble_device)
                self._ble_model = session.model
                if not self._ble_display_name:
                    self._ble_display_name = session.display_name or session.model
        except Exception:  # noqa: BLE001
            LOGGER.debug("Napoleon Home %s: metadata read failed (best-effort)", mac)

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
            outcome = await self._async_probe_ble(self._mac or "")
            if outcome == ProbeOutcome.PROVISIONED:
                return await self.async_step_key_retrieval()
            if outcome == ProbeOutcome.NOT_PROVISIONED:
                return await self.async_step_provision_guide()
            errors["base"] = "reset_not_detected" if outcome == ProbeOutcome.BONDED_TO_OTHER else "cannot_connect"

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
            outcome = await self._async_probe_ble(self._mac or "")
            if outcome == ProbeOutcome.PROVISIONED:
                return await self.async_step_key_retrieval()
            if outcome == ProbeOutcome.BONDED_TO_OTHER:
                return await self.async_step_factory_reset_guide()
            errors["base"] = "ble_not_provisioned" if outcome == ProbeOutcome.NOT_PROVISIONED else "cannot_connect"

        return self.async_show_form(
            step_id="provision_guide",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._name or self._mac or ""},
        )

    @contextlib.asynccontextmanager
    async def _handle_api_errors(self, errors: dict[str, str]):  # type: ignore[return]
        """Async context manager that maps Napoleon API exceptions to form error keys."""
        try:
            yield
        except NapoleonHomeApiClientAuthenticationError:
            errors["base"] = "invalid_auth"
        except NapoleonHomeApiClientCommunicationError:
            errors["base"] = "cannot_connect"
        except NapoleonHomeApiClientError:
            errors["base"] = "unknown"
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected exception during Napoleon Home API call")
            errors["base"] = "unknown"

    async def _async_probe_and_route(self) -> config_entries.ConfigFlowResult:
        """Probe the grill's provisioning state and route to the appropriate next step.

        Used by ``async_step_bluetooth_confirm`` after the user taps Submit.
        Calls ``_async_probe_ble``, applies the display name from GATT if retrieved,
        then routes based on the outcome.

        """
        outcome = await self._async_probe_ble(self._mac or "")
        if self._ble_display_name:
            self._name = self._ble_display_name
            self.context["title_placeholders"] = {"name": self._name}
        if outcome == ProbeOutcome.BONDED_TO_OTHER:
            LOGGER.info(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=factory_reset address=%s",
                self._mac,
            )
            return await self.async_step_factory_reset_guide()
        if outcome == ProbeOutcome.NOT_PROVISIONED:
            LOGGER.info(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=provision_guide address=%s",
                self._mac,
            )
            return await self.async_step_provision_guide()
        if outcome == ProbeOutcome.UNREACHABLE:
            LOGGER.warning(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=key_retrieval "
                "reason=probe_inconclusive address=%s",
                self._mac,
            )
        else:
            LOGGER.info(
                "Napoleon Home: setup_stage=bluetooth_step_branch branch=key_retrieval address=%s",
                self._mac,
            )
        return await self.async_step_key_retrieval()

    async def _async_probe_ble(self, mac: str) -> ProbeOutcome:
        """Connect, bond, and probe provisioning state.

        Returns a ProbeOutcome. Reads DSN and display name or model string from
        GATT during the session (best-effort; failures are suppressed).

        """
        ble_device = async_ble_device_from_address(self.hass, mac, connectable=True)
        if ble_device is None:
            return ProbeOutcome.UNREACHABLE
        try:
            async with NapoleonHomeBLESession(mac) as session:
                # Catch AlreadyBondedError so we can still harvest session.model (0x2A00),
                # which connect() reads before pair(). DSN and display_name are read after
                # pair() and are unavailable in the bonded case.
                bonded = False
                try:
                    await session.connect(ble_device)
                except NapoleonHomeAlreadyBondedError:
                    bonded = True

                if self._ble_dsn is None:
                    self._ble_dsn = session.dsn
                    if self._ble_dsn is None:
                        LOGGER.debug("Napoleon Home %s: DSN unavailable — will match by MAC", mac)
                if session.display_name:
                    self._ble_display_name = session.display_name
                elif not self._ble_display_name and session.model:
                    self._ble_display_name = session.model

                if bonded:
                    return ProbeOutcome.BONDED_TO_OTHER

                provisioned = await session.check_provisioned()
                LOGGER.debug("Napoleon Home %s: check_provisioned=%s", mac, provisioned)
                if provisioned is True:
                    return ProbeOutcome.PROVISIONED
                if provisioned is False:
                    return ProbeOutcome.NOT_PROVISIONED
                return ProbeOutcome.UNREACHABLE
        except NapoleonHomeAlreadyBondedError:
            return ProbeOutcome.BONDED_TO_OTHER
        except Exception:  # noqa: BLE001
            LOGGER.debug("Napoleon Home %s: BLE probe failed — treating as inconclusive", mac)
            return ProbeOutcome.UNREACHABLE

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
        DSN (from the GATT read) when known. If the DSN is unknown or not found in
        the account, every account device's key is tried in turn — ``_async_finish``
        performs real BLE authentication, so the grill itself decides the match.

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

            # Store form values before the API call so the form retains them on error retry.
            self._username = username.strip()
            self._password = password
            self._region_key = region_key

            devices: list[tuple[str, str, str]] = []
            async with self._handle_api_errors(errors):
                region = AYLA_REGIONS[region_key]
                http_session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, http_session)
                devices, access_token, refresh_token, token_expiry = await client.async_list_devices(username, password)

            if "base" not in errors:
                # Match device: prefer DSN from GATT read. If unknown or stale,
                # try every account device and let real BLE auth decide — more
                # robust than guessing a MAC offset.
                match: tuple[str, str, str] | None = None
                if self._ble_dsn:
                    match = next((d for d in devices if d[0] == self._ble_dsn), None)
                    if match is not None:
                        LOGGER.debug("Napoleon Home: matched device by DSN %s", self._ble_dsn)
                    else:
                        LOGGER.warning(
                            "Napoleon Home: DSN %s not found in account — trying all %d device(s)",
                            self._ble_dsn,
                            len(devices),
                        )

                candidates = [match] if match is not None else devices

                if not candidates:
                    errors["base"] = "no_devices_found"
                else:
                    self._access_token = access_token
                    self._refresh_token = refresh_token
                    self._token_expiry = token_expiry
                    try:
                        result, errors = await self._async_try_candidates(candidates, client, access_token)
                    except NapoleonHomeNotProvisionedError:
                        return await self.async_step_provision_guide()
                    if result is not None:
                        return result

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

    async def _async_try_candidates(
        self,
        candidates: list[tuple[str, str, str]],
        client: NapoleonHomeApiClient,
        access_token: str,
    ) -> tuple[config_entries.ConfigFlowResult | None, dict[str, str]]:
        """Try each device candidate in order, returning on the first success.

        Returns ``(result, {})`` when a candidate authenticates, or
        ``(None, errors)`` when all candidates fail. Raises
        ``NapoleonHomeNotProvisionedError`` for caller routing to provision_guide.

        """
        errors: dict[str, str] = {}
        key_rejected = False
        for dsn, device_name, _ in candidates:
            LOGGER.debug("Napoleon Home: key_retrieval attempting dsn=%s name=%s", dsn, device_name)
            try:
                local_key, local_key_id = await client.async_fetch_key(access_token, dsn)
                return await self._async_finish(dsn, device_name, local_key, local_key_id), {}
            except NapoleonHomeNotProvisionedError:
                raise
            except ConfigEntryAuthFailed:
                LOGGER.debug("Napoleon Home: DSN %s key rejected — trying next candidate", dsn)
                key_rejected = True
            except NapoleonHomeMacAddressRequiredError:
                errors["base"] = "ble_discovery_required"
                break
            except NapoleonHomeBLEConnectionError:
                errors["base"] = "ble_auth_failed"
                break
            except HomeAssistantError, NapoleonHomeApiClientError:
                errors["base"] = "cannot_connect"
                break
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception finalising Napoleon Home setup")
                errors["base"] = "unknown"
                break
        errors["base"] = "ble_key_rejected" if key_rejected else "no_devices_found"
        return None, errors

    async def _async_finish(
        self,
        dsn: str,
        device_name: str,
        local_key: str,
        local_key_id: int,
    ) -> config_entries.ConfigFlowResult:
        """
        Validate the local key via BLE and create or update the hub entry.

        Resolves connectable MAC candidates (offset variants + discovered services),
        then authenticates with each until one accepts the key. Creates or updates
        the hub config entry and adds the grill to ``entry.data[CONF_DEVICES]``.

        Args:
            dsn: Ayla device serial number of the grill to configure.
            device_name: Display name used as the device's friendly name.
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
            for device in entry.data.get(CONF_DEVICES, {}).values():
                if device.get(CONF_DSN) == dsn:
                    return self.async_abort(reason="already_configured")

        # Resolve connectable MAC candidates (offset variants + name-matched discoveries).
        mac_candidates = await self._async_resolve_valid_mac(device_name)

        # Full BLE authentication — try each candidate until one accepts the key.
        mac: str | None = None
        last_auth_err: ConfigEntryAuthFailed | None = None
        had_ble_failure = False
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
                LOGGER.warning(
                    "Napoleon Home %s: grill already bonded to another device — routing to factory reset guide",
                    candidate,
                )
                return await self.async_step_factory_reset_guide()
            except NapoleonHomeNotProvisionedError:
                raise
            except ConfigEntryAuthFailed as err:
                LOGGER.debug("Napoleon Home %s: auth rejected (s:4) — trying next candidate", candidate)
                last_auth_err = err
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Napoleon Home %s: BLE auth error — skipping candidate: %s", candidate, err)
                had_ble_failure = True

        if mac is None:
            if had_ble_failure:
                msg = f"Napoleon Home {mac_candidates[0]}: BLE connection failed during authentication"
                raise NapoleonHomeBLEConnectionError(msg)
            if last_auth_err is not None:
                raise last_auth_err
            msg = f"Napoleon Home {mac_candidates[0]}: grill not discoverable for authentication"
            raise HomeAssistantError(msg)

        self._mac = mac
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
        device_data = {
            CONF_DSN: dsn,
            CONF_LOCAL_KEY: local_key,
            CONF_LOCAL_KEY_ID: local_key_id,
            "name": title,
        }

        # Check whether a hub entry for this account already exists.
        existing_hub = next(
            (e for e in self.hass.config_entries.async_entries(DOMAIN) if e.unique_id == hub_unique_id),
            None,
        )

        if existing_hub is not None:
            if mac in existing_hub.data.get(CONF_DEVICES, {}):
                return self.async_abort(reason="already_configured")
            updated_devices = {**existing_hub.data.get(CONF_DEVICES, {}), mac: device_data}
            self.hass.config_entries.async_update_entry(
                existing_hub,
                data={**existing_hub.data, **hub_data, CONF_DEVICES: updated_devices},
            )
            return self.async_abort(reason="device_added_to_account")

        await self.async_set_unique_id(hub_unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=f"Napoleon Home ({self._username})",
            data={**hub_data, CONF_DEVICES: {mac: device_data}},
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
            if name.startswith(NAPOLEON_NAME_PREFIXES):
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

        Signs in once and refreshes local keys for ALL devices in the hub,
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

            devices = reauth_entry.data.get(CONF_DEVICES, {})
            # Only include devices that have a DSN — devices migrated from v1 may
            # have an empty string if the subentry lacked the field.
            mac_dsn_pairs = [(mac, d[CONF_DSN]) for mac, d in devices.items() if d.get(CONF_DSN)]
            dsns = [dsn for _, dsn in mac_dsn_pairs]

            async with self._handle_api_errors(errors):
                region = AYLA_REGIONS[region_key]
                session = async_get_clientsession(self.hass)
                client = NapoleonHomeApiClient(region, session)
                keys, access_token, refresh_token, token_expiry = await client.async_refresh_local_keys(
                    username, password, dsns
                )
            if "base" not in errors:
                updated_devices = dict(devices)
                for (mac, _), (local_key, local_key_id) in zip(mac_dsn_pairs, keys, strict=True):
                    updated_devices[mac] = {
                        **updated_devices[mac],
                        CONF_LOCAL_KEY: local_key,
                        CONF_LOCAL_KEY_ID: local_key_id,
                    }
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_REGION: region_key,
                        CONF_USERNAME: username,
                        CONF_ACCESS_TOKEN: access_token,
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_TOKEN_EXPIRY: token_expiry,
                        CONF_DEVICES: updated_devices,
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
