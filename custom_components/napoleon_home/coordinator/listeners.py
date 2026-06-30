"""
BLE connection lifecycle mixin for napoleon_home.

Separates the BLE connection management, authentication handshake, and GATT
notification handling from the DataUpdateCoordinator polling logic. Mixed into
``NapoleonHomeDataUpdateCoordinator`` in ``base.py``.

Protocol overview:
    - Advertisement callback reconnects the grill whenever it powers on.
    - ``_connect_and_run``: creates a ``NapoleonHomeBLESession``, connects,
      registers data handlers, and calls ``session.authenticate()``.
    - Data handlers ``_handle_gpr`` / ``_handle_odp`` / ``_handle_opr`` /
      ``_handle_ukn`` are registered on the session and called per opcode.
    - All writes go through ``_send_msg`` which delegates to the session.

For more information on the BLE protocol:
See _handover/CLAUDE.md — Protocol section.
"""

from __future__ import annotations

import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, BleakNotFoundError

from custom_components.napoleon_home.bluetooth import (
    NapoleonHomeAlreadyBondedError,
    NapoleonHomeBLESession,
    NapoleonHomeNotProvisionedError,
)
from custom_components.napoleon_home.const import (
    CONF_DEVICES,
    DOMAIN,
    LOGGER,
    MAX_CONNECT_FAILURES,
    POLL_PROPS,
    PROP_BSMODE,
    PROP_TYPE_BOOL,
)
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
)
from homeassistant.core import CALLBACK_TYPE, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry, NapoleonHomeGrillState
    from homeassistant.core import HomeAssistant


def _issue_id(prefix: str, mac: str) -> str:
    return f"{prefix}_{mac.replace(':', '_').lower()}"


class NapoleonHomeBLEMixin:
    """
    BLE connection lifecycle mixin for the Napoleon Prestige grill coordinator.

    Provides advertisement detection, BLE connection with retry, Ayla Local Control
    v2 HMAC authentication (via ``NapoleonHomeBLESession``), and notification routing.

    Requires the host class to provide:
        - ``self.hass`` (HomeAssistant)
        - ``self.config_entry`` (NapoleonHomeConfigEntry)
        - ``self.data`` (NapoleonHomeGrillState)
        - ``self.async_set_updated_data(data)``

    Initialise BLE state by calling ``_init_ble(mac, local_key)`` from ``__init__``.

    """

    if TYPE_CHECKING:
        hass: HomeAssistant
        config_entry: NapoleonHomeConfigEntry
        data: NapoleonHomeGrillState
        update_interval: timedelta | None
        _poll_interval: int

        def async_set_updated_data(self, data: NapoleonHomeGrillState) -> None:  # noqa: D102
            ...

        async def async_refresh(self) -> None:  # noqa: D102
            ...

    def _init_ble(self, mac: str, local_key: str) -> None:
        """
        Initialise BLE connection state.

        Called from the coordinator ``__init__`` after the DataUpdateCoordinator
        base class is initialised.

        Args:
            mac: Bluetooth MAC address of the grill (e.g. ``"AA:BB:CC:DD:EE:FF"``).
            local_key: Base64-encoded BLE authentication key from the Ayla cloud.

        """
        self._mac = mac
        self._local_key = local_key
        self._session: NapoleonHomeBLESession | None = None
        self._authenticated: bool = False
        self._connecting: bool = False
        self._connect_failures: int = 0
        self._bt_cancel_callback: CALLBACK_TYPE | None = None
        self._stopping: bool = False
        self._circuit_open: bool = False
        self._bsmode_desired: int = 1

    # Connection state

    @property
    def connected(self) -> bool:
        """Return True if the BLE session is currently connected."""
        return self._session is not None and self._session.connected

    @property
    def authenticated(self) -> bool:
        """Return True if the grill session is fully authenticated."""
        return self.connected and self._authenticated

    # Advertisement → connection

    def _register_bt_callback(self) -> None:
        """
        Register an advertisement callback to reconnect when the grill powers on.

        Called after every disconnect (clean or error) so the coordinator
        reconnects automatically the next time an advertisement is seen.
        Cancels any existing callback first to ensure at most one is ever active.
        """
        if self._bt_cancel_callback is not None:
            self._bt_cancel_callback()
            self._bt_cancel_callback = None
        LOGGER.debug("Napoleon Home %s: waiting for advertisement", self._mac)
        LOGGER.debug("Napoleon Home %s: setup_stage=bt_callback_registered scan_mode=active", self._mac)
        self._bt_cancel_callback = async_register_callback(
            self.hass,
            self._on_advertisement,
            {"address": self._mac, "connectable": True},
            BluetoothScanningMode.ACTIVE,
        )

    @callback
    def _on_advertisement(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """
        Handle a new advertisement from the Napoleon grill.

        Cancels the advertisement callback immediately, then schedules the BLE
        connection task so the event loop is not blocked.

        Args:
            service_info: Bluetooth advertisement data including the BLE device.
            change: The type of advertisement change that fired this callback.

        """
        if self._connecting or self.connected:
            LOGGER.debug(
                "Napoleon Home %s: setup_stage=advertisement_ignored state=%s rssi=%s change=%s",
                self._mac,
                "connecting" if self._connecting else "connected",
                service_info.advertisement.rssi,
                change,
            )
            return
        if self._bt_cancel_callback is not None:
            self._bt_cancel_callback()
            self._bt_cancel_callback = None
        LOGGER.debug(
            "Napoleon Home %s: advertisement received (rssi=%s), connecting",
            self._mac,
            service_info.advertisement.rssi,
        )
        self.config_entry.async_create_background_task(
            self.hass,
            self._connect_and_run(service_info.device),
            f"napoleon_home_connect_{self._mac}",
        )

    async def _connect_and_run(self, device: BLEDevice) -> None:
        """
        Establish a BLE session, authenticate, and maintain the connection.

        Creates a ``NapoleonHomeBLESession``, connects, registers the data
        notification handlers, then calls ``session.authenticate()``. Any error
        during connect or auth increments the failure counter. After
        ``MAX_CONNECT_FAILURES`` consecutive failures the circuit breaker opens
        (``_circuit_open = True``) and auto-reconnect stops. Reload the entry to
        resume.

        Catches ``NapoleonHomeNotProvisionedError`` specially — logs a warning
        and disconnects without incrementing the failure counter, so that an
        unprovisioned grill doesn't trip the circuit breaker while the user
        completes provisioning in the Napoleon app.

        Args:
            device: The ``BLEDevice`` to connect to.

        """
        if self._connecting or self.connected:
            return
        self._connecting = True
        try:
            LOGGER.debug(
                "Napoleon Home %s: BLE connect (failure_count=%d/%d)",
                self._mac,
                self._connect_failures,
                MAX_CONNECT_FAILURES,
            )

            session = NapoleonHomeBLESession(self._mac)
            try:
                await session.connect(
                    device,
                    on_disconnect=self._on_disconnect,
                    ble_device_callback=lambda: (
                        async_ble_device_from_address(self.hass, self._mac, connectable=True) or device
                    ),
                )
            except (BleakNotFoundError, TimeoutError) as err:
                LOGGER.debug("Napoleon Home %s: could not connect — %s", self._mac, err)
                self._connecting = False
                self._on_disconnect(None)
                return
            except Exception:
                await session.disconnect()
                raise

            if self._stopping:
                # Shutdown raced the connect; disconnect cleanly without counting a failure.
                with contextlib.suppress(Exception):
                    await session.disconnect()
                return

            # Session is live — make it visible and register data handlers.
            self._session = session
            session.register_handler("gpr", self._handle_gpr)
            session.register_handler("Odp", self._handle_odp)
            session.register_handler("opr", self._handle_opr)
            session.register_handler("ukn", self._handle_ukn)

            await session.authenticate(self._local_key)

            # Auth succeeded — clear any open repair issues.
            self._authenticated = True
            self._connect_failures = 0
            ir.async_delete_issue(self.hass, DOMAIN, _issue_id("already_bonded", self._mac))
            ir.async_delete_issue(self.hass, DOMAIN, _issue_id("not_provisioned", self._mac))
            self.update_interval = timedelta(seconds=self._poll_interval)
            self.config_entry.async_create_background_task(
                self.hass,
                self.async_refresh(),
                f"napoleon_home_initial_poll_{self._mac}",
            )
            await self._async_apply_post_auth_defaults()

        except NapoleonHomeNotProvisionedError:
            LOGGER.warning(
                "Napoleon Home %s: grill not provisioned (s:6) — provision via Napoleon app then confirm the repair",
                self._mac,
            )
            self._circuit_open = True
            device_name = self.config_entry.data.get(CONF_DEVICES, {}).get(self._mac, {}).get("name", self._mac)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                _issue_id("not_provisioned", self._mac),
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="not_provisioned",
                translation_placeholders={"name": device_name},
                data={"entry_id": self.config_entry.entry_id, "mac": self._mac},
            )
            await self._disconnect_session()

        except ConfigEntryAuthFailed:
            LOGGER.warning(
                "Napoleon Home %s: auth failed due to rotated/rejected BLE key; starting reauth",
                self._mac,
            )
            self.config_entry.async_start_reauth(self.hass)
            await self._disconnect_session()
            return

        except NapoleonHomeAlreadyBondedError:
            LOGGER.error(
                "Napoleon Home %s: grill is bonded to another device (ATT 0x05) — "
                "factory reset the grill then confirm the repair in HA",
                self._mac,
            )
            self._circuit_open = True
            device_name = self.config_entry.data.get(CONF_DEVICES, {}).get(self._mac, {}).get("name", self._mac)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                _issue_id("already_bonded", self._mac),
                is_fixable=True,
                is_persistent=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="already_bonded",
                translation_placeholders={"name": device_name},
                data={"entry_id": self.config_entry.entry_id, "mac": self._mac},
            )
            await self._disconnect_session()
            return

        except Exception:  # noqa: BLE001
            self._connect_failures += 1
            if self._connect_failures >= MAX_CONNECT_FAILURES:
                LOGGER.error(
                    "Napoleon Home %s: %d consecutive connection failures — stopping auto-reconnect; "
                    "reload the integration entry to retry",
                    self._mac,
                    self._connect_failures,
                )
                self._circuit_open = True
                await self._disconnect_session()
            else:
                LOGGER.warning(
                    "Napoleon Home %s: connection attempt failed — will retry on next advertisement", self._mac
                )
                await self._disconnect_session(notify_on_error=True)
        finally:
            self._connecting = False

    async def _disconnect_session(self, *, notify_on_error: bool = False) -> None:
        """Disconnect the active session and reset auth state.

        If no session is active, calls _on_disconnect directly so the BT
        callback is re-registered (unless the circuit is open or we are stopping).
        When notify_on_error=True, also calls _on_disconnect if the disconnect
        call itself raises (used on non-fatal retry paths to keep the reconnect
        cycle alive).
        """
        if self._session is not None:
            session_ref = self._session
            self._session = None
            self._authenticated = False
            try:
                await session_ref.disconnect()
            except Exception:  # noqa: BLE001
                if notify_on_error:
                    self._on_disconnect(None)
        else:
            self._on_disconnect(None)

    async def _async_apply_post_auth_defaults(self) -> None:
        """Apply desired defaults after authentication without affecting auth success."""
        try:
            await self._send_msg("Opr", {"n": PROP_BSMODE, "t": PROP_TYPE_BOOL, "v": self._bsmode_desired})
        except Exception as err:  # noqa: BLE001
            LOGGER.warning(
                "Napoleon Home %s: failed to apply post-auth defaults (BSMODE=%s): %s",
                self._mac,
                self._bsmode_desired,
                err,
            )

    @callback
    def async_close_circuit(self) -> None:
        """Re-enable BLE reconnection after a circuit-breaker repair is confirmed."""
        self._circuit_open = False
        if not self._stopping and not self.connected and not self._connecting:
            self._register_bt_callback()

    @callback
    def _on_disconnect(self, client: BleakClientWithServiceCache | None) -> None:
        """
        Handle a BLE disconnection.

        Clears all connection state and re-registers the advertisement callback
        so the coordinator reconnects when the grill powers on again. Does not
        re-register the callback during an intentional shutdown (``_stopping``) or
        when the circuit breaker has opened after repeated failures (``_circuit_open``).

        Args:
            client: The disconnected BleakClient, or None if called manually.

        """
        self._session = None
        self._authenticated = False
        if self.update_interval is not None:
            # Disconnected from an authenticated session — reset so the next reconnect
            # starts with a clean failure count rather than inheriting stale retries.
            self._connect_failures = 0
        self.update_interval = None
        LOGGER.debug("Disconnected from Napoleon Home %s — waiting for advertisement", self._mac)
        if not self._stopping and not self._circuit_open:
            self._register_bt_callback()

    # GATT notification handlers (registered on the session per-opcode)

    def _handle_gpr(self, msg: dict[str, Any]) -> None:
        """Handle a ``gpr`` polled-property response from the grill."""
        payload: dict[str, Any] = msg.get("p") or {}
        name = payload.get("n")
        value = payload.get("v")
        if name is not None and value is not None:
            LOGGER.debug("Napoleon Home %s: gpr %s=%r", self._mac, name, value)
            self.data.update_from_property(name, value)
            self.async_set_updated_data(self.data)

    def _handle_odp(self, msg: dict[str, Any]) -> None:
        """Handle an ``Odp`` push notification from the grill."""
        payload: dict[str, Any] = msg.get("p") or {}
        seq: int = msg.get("i", 0)
        name = payload.get("n")
        value = payload.get("v")
        if name is not None and value is not None:
            self.config_entry.async_create_background_task(
                self.hass,
                self._send_msg("odp", {"n": name}, ack_seq=seq),
                f"napoleon_home_odp_ack_{self._mac}",
            )
            if name == PROP_BSMODE and int(value) != self._bsmode_desired:
                LOGGER.debug(
                    "Napoleon Home %s: push %s=%r (seq=%d) mismatches desired=%s; reasserting",
                    self._mac,
                    name,
                    value,
                    seq,
                    self._bsmode_desired,
                )
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._send_msg("Opr", {"n": PROP_BSMODE, "t": PROP_TYPE_BOOL, "v": self._bsmode_desired}),
                    f"napoleon_home_bsmode_reassert_{self._mac}",
                )
                return
            LOGGER.debug("Napoleon Home %s: push %s=%r (seq=%d)", self._mac, name, value, seq)
            self.data.update_from_property(name, value)
            self.async_set_updated_data(self.data)

    def _handle_opr(self, msg: dict[str, Any]) -> None:
        """Handle an ``opr`` write-ACK from the grill (logged as debug)."""
        payload: dict[str, Any] = msg.get("p") or {}
        LOGGER.debug("Napoleon Home %s: opr ack (n=%s)", self._mac, payload.get("n"))

    def _handle_ukn(self, msg: dict[str, Any]) -> None:
        """Handle a ``ukn`` rejection — the grill received an invalid command."""
        LOGGER.warning(
            "Napoleon Home %s: ukn — invalid command rejected by grill (s=%s)",
            self._mac,
            msg.get("s"),
        )

    # GATT write helper

    async def _send_msg(
        self,
        opcode: str,
        payload: dict[str, Any] | None = None,
        *,
        ack_seq: int | None = None,
    ) -> None:
        """
        Encode and write a protocol message to the inbox characteristic.

        Delegates to ``NapoleonHomeBLESession.write_msg``. Drops silently if the
        session is not connected.

        Args:
            opcode: The Ayla protocol opcode string (e.g. ``"Oac"``, ``"Gpr"``).
            payload: Optional payload dict to include in the message envelope.
            ack_seq: When set, use this sequence number verbatim (for ``odp`` ACK
                replies that must echo the received message's ``i`` value). When
                None, the session's internal counter is auto-incremented.

        """
        if self._session is None:
            LOGGER.debug(
                "Napoleon Home %s: _send_msg(%s) called while disconnected — dropped",
                self._mac,
                opcode,
            )
            return
        await self._session.write_msg(opcode, payload, ack_seq=ack_seq)

    async def _poll_properties(self) -> None:
        """
        Send a ``Gpr`` poll request for every property in ``POLL_PROPS``.

        Called by ``_async_update_data`` on each coordinator refresh cycle.
        """
        for name in POLL_PROPS:
            await self._send_msg("Gpr", {"n": name})

    async def async_set_property(self, name: str, type_code: int, value: Any) -> None:
        """
        Write a property value to the grill via an ``Opr`` command.

        Called by entity platforms (switch, select, number, button) when the user
        changes a setting in Home Assistant.

        Args:
            name: The Ayla property name to set (e.g. ``"TUNIT"``, ``"LCD_OFF"``).
            type_code: The Ayla type code (from ``PROP_TYPE_*`` constants).
            value: The value to set, matching the type indicated by ``type_code``.

        """
        await self._send_msg("Opr", {"n": name, "t": type_code, "v": value})

    async def async_set_bsmode(self, value: int) -> None:
        """Write BSMODE and persist as the desired value so re-assert logic uses it."""
        self._bsmode_desired = value
        await self._send_msg("Opr", {"n": PROP_BSMODE, "t": PROP_TYPE_BOOL, "v": value})

    async def _shutdown_ble(self) -> None:
        """
        Tear down BLE state cleanly.

        Cancels any pending advertisement callback and disconnects the BLE session.
        Sets ``_stopping`` before disconnecting so that ``_on_disconnect`` does not
        re-register the advertisement callback after the entry is unloaded.

        Called from ``NapoleonHomeDataUpdateCoordinator.async_shutdown``.
        """
        LOGGER.debug("Napoleon Home %s: shutting down BLE", self._mac)
        self._stopping = True
        if self._bt_cancel_callback is not None:
            self._bt_cancel_callback()
            self._bt_cancel_callback = None
        if self._session is not None:
            await self._session.disconnect()
