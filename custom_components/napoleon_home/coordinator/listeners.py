"""
BLE connection lifecycle mixin for napoleon_home.

Separates the BLE connection management, authentication handshake, and GATT
notification handling from the DataUpdateCoordinator polling logic. Mixed into
``NapoleonHomeDataUpdateCoordinator`` in ``base.py``.

Protocol overview:
    - Advertisement callback reconnects the grill whenever it powers on.
    - ``_connect_and_run``: establishes BLE, subscribes to outbox, authenticates.
    - ``_authenticate``: sends ``Oac t:1``, awaits HMAC challenge, verifies ``Oac t:2``.
    - ``_on_notification``: routes ``oac``, ``gpr``, ``Odp``, ``opr``, ``ukn`` messages.
    - All writes go through ``_send_msg`` which fragments payloads and serialises via
      an ``asyncio.Lock``.

For more information on the BLE protocol:
See _handover/CLAUDE.md — Protocol section.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, BleakNotFoundError, establish_connection

from custom_components.napoleon_home.bluetooth import (
    NapoleonHomeOutboxAssembler,
    compute_hmac,
    decode_msg,
    encode_inbox,
    make_msg,
)
from custom_components.napoleon_home.const import (
    AUTH_TIMEOUT,
    AUTH_USER,
    BLE_AUTH_STATUS_NOT_PROVISIONED,
    BLE_AUTH_STATUS_REJECTED,
    DOMAIN,
    INBOX_UUID,
    LOGGER,
    MAX_CONNECT_FAILURES,
    OUTBOX_UUID,
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

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry, NapoleonHomeGrillState
    from homeassistant.core import HomeAssistant


class NapoleonHomeBLEMixin:
    """
    BLE connection lifecycle mixin for the Napoleon Prestige grill coordinator.

    Provides advertisement detection, BLE connection with retry, Ayla Local Control
    v2 HMAC authentication, fragmented GATT write helpers, and notification routing.

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
        self._client: BleakClientWithServiceCache | None = None
        self._mtu: int = 512
        self._assembler = NapoleonHomeOutboxAssembler()
        self._write_lock = asyncio.Lock()
        self._auth_ok = asyncio.Event()
        self._seq: int = 0
        self._connecting: bool = False
        self._connect_failures: int = 0
        self._bt_cancel_callback: CALLBACK_TYPE | None = None
        self._stopping: bool = False
        self._circuit_open: bool = False
        self._bsmode_desired: int = 1
        self._auth_rejected: asyncio.Event = asyncio.Event()

    # Connection state

    @property
    def connected(self) -> bool:
        """Return True if the BLE client is currently connected."""
        return self._client is not None and self._client.is_connected

    @property
    def authenticated(self) -> bool:
        """Return True if the grill session is fully authenticated."""
        return self.connected and self._auth_ok.is_set()

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
            # A connection is already in progress or established. Discard this
            # advertisement — leave the callback registered so the next one fires.
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
        Establish a BLE connection, authenticate, and maintain the session.

        Uses ``establish_connection`` (``bleak_retry_connector``) for robust BLE
        connection with automatic slot-draining, backoff, and error classification.
        After a successful connect, subscribes to outbox notifications and performs
        the Ayla Local Control v2 authentication handshake.

        Any error during connect or auth increments the failure counter. After
        ``MAX_CONNECT_FAILURES`` consecutive failures the circuit breaker opens
        (``_circuit_open = True``) and auto-reconnect stops. Reload the entry to
        resume.

        Returns immediately without counting a failure if ``_stopping`` is set
        after a successful connect (entry is being unloaded).

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
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    device,
                    self._mac,
                    disconnected_callback=self._on_disconnect,
                    max_attempts=1,
                    ble_device_callback=lambda: (
                        async_ble_device_from_address(self.hass, self._mac, connectable=True) or device
                    ),
                )
            except (BleakNotFoundError, TimeoutError) as err:
                LOGGER.debug("Napoleon Home %s: could not connect — %s", self._mac, err)
                self._connecting = False
                self._on_disconnect(None)
                return
            if self._stopping:
                # Shutdown raced the connect; disconnect cleanly and exit without
                # incrementing the failure counter.
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return
            LOGGER.debug("Napoleon Home %s: BLE connected, subscribing to outbox", self._mac)
            self._seq = 0
            self._assembler = NapoleonHomeOutboxAssembler()
            # Assign self._client before sleeping so _shutdown_ble can disconnect us
            # if it races this window, and so immediate Odp ACKs from start_notify
            # can be sent via _send_msg.
            self._client = client
            # Bond with the grill so the BLE link is encrypted before any INBOX write.
            # INBOX (01000001-fe28) requires an encrypted, bonded link — ATT error 0x05
            # is returned otherwise.  On first run this triggers Just Works SMP (no PIN).
            # On subsequent runs BlueZ uses the stored LTK and pair() returns immediately.
            try:
                await client.pair()
                LOGGER.debug("Napoleon Home %s: BLE link bonded/encrypted", self._mac)
            except Exception:  # noqa: BLE001
                # pair() raises if already bonded ("already paired") — that is fine;
                # the stored LTK means the connection is already encrypted.  Any other
                # exception is logged as a warning but we continue: _authenticate() will
                # fail with a timeout if the link is genuinely not encrypted, which
                # increments the failure counter and triggers a reconnect/retry.
                LOGGER.debug("Napoleon Home %s: pair() raised — proceeding (already bonded?)", self._mac)
            await client.start_notify(OUTBOX_UUID, self._on_notification)
            # The grill expects a complete JSON object in a single INBOX write; it disconnects on
            # a partial fragment.  The default ATT MTU (23) forces fragmentation into ~4 chunks.
            # Explicitly negotiate a larger MTU so the full Oac payload fits in one write.
            # _acquire_mtu() is on the bluezdbus backend; other backends set mtu_size directly.
            _acquire = getattr(getattr(client, "_backend", client), "_acquire_mtu", None)
            if callable(_acquire):
                await _acquire()  # type: ignore[misc]
                self._mtu = client.mtu_size
            LOGGER.debug("Napoleon Home %s: outbox subscribed (MTU=%d)", self._mac, self._mtu)
            await self._authenticate()
            await self._async_apply_post_auth_defaults()
        except ConfigEntryAuthFailed:
            LOGGER.warning(
                "Napoleon Home %s: auth failed due to rotated/rejected BLE key; starting reauth",
                self._mac,
            )
            self.config_entry.async_start_reauth(self.hass)
            if self._client is not None:
                client_ref = self._client
                self._client = None
                self._auth_ok.clear()
                with contextlib.suppress(Exception):
                    await client_ref.disconnect()
            else:
                self._on_disconnect(None)
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
                # Open the circuit breaker so _on_disconnect does not restart auto-reconnect
                # when the grill eventually drops this connection.
                self._circuit_open = True
                if self._client is not None:
                    # Post-connect failure at the limit: disconnect fires _on_disconnect which
                    # sees _circuit_open=True and skips re-registration.
                    client_ref = self._client
                    self._client = None
                    self._auth_ok.clear()
                    with contextlib.suppress(Exception):
                        await client_ref.disconnect()
                # If self._client is None, establish_connection already drained the slot.
            else:
                LOGGER.warning(
                    "Napoleon Home %s: connection attempt failed — will retry on next advertisement", self._mac
                )
                if self._client is not None:
                    # Post-connect failure (auth timeout, start_notify error, etc.):
                    # explicit disconnect triggers _on_disconnect via the BleakClient
                    # callback, which clears state and re-registers the advertisement
                    # callback so the grill sees a clean teardown before we retry.
                    client_ref = self._client
                    self._client = None
                    self._auth_ok.clear()
                    try:
                        await client_ref.disconnect()
                    except Exception:  # noqa: BLE001
                        # disconnect() raised before the BleakClient callback could fire;
                        # call _on_disconnect manually so auto-reconnect can continue.
                        self._on_disconnect(None)
                else:
                    # establish_connection itself failed and already called
                    # wait_for_disconnect internally before raising, so the BlueZ slot
                    # is drained. Just re-register the advertisement callback.
                    self._on_disconnect(None)
        finally:
            self._connecting = False

    async def _authenticate(self) -> None:
        """
        Perform the Ayla Local Control v2 HMAC-SHA256 authentication handshake.

        Sends ``Oac t:1`` (challenge request) and waits for the grill to reply
        with a nonce on the outbox. The notification callback computes the HMAC
        response and sends ``Oac t:2``. This method then waits for ``oac t:2``
        (auth success) to be signalled via the ``_auth_ok`` event.
        """
        self._auth_ok.clear()
        self._auth_rejected.clear()
        LOGGER.debug("Napoleon Home %s: sending auth challenge request (Oac t:1)", self._mac)
        await self._send_msg("Oac", {"t": 1, "i": AUTH_USER})

        ok_task = asyncio.ensure_future(self._auth_ok.wait())
        rejected_task = asyncio.ensure_future(self._auth_rejected.wait())
        done, pending = await asyncio.wait(
            {ok_task, rejected_task},
            timeout=AUTH_TIMEOUT,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()

        if self._auth_rejected.is_set():
            LOGGER.warning("Napoleon Home %s: BLE auth rejected (s:4) — local key has rotated", self._mac)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="ble_auth_rejected",
            )
        if not done:
            LOGGER.warning("Authentication timed out for Napoleon Home %s", self._mac)
            raise TimeoutError("Authentication timed out")

        self._connect_failures = 0
        LOGGER.debug("Napoleon Home %s: authenticated", self._mac)
        self.update_interval = timedelta(seconds=self._poll_interval)
        self.config_entry.async_create_background_task(
            self.hass,
            self.async_refresh(),
            f"napoleon_home_initial_poll_{self._mac}",
        )

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
        self._client = None
        self._auth_ok.clear()
        self._auth_rejected.clear()
        if self.update_interval is not None:
            # Disconnected from an authenticated session — reset so the next reconnect
            # starts with a clean failure count rather than inheriting stale retries.
            self._connect_failures = 0
        self.update_interval = None
        LOGGER.debug("Disconnected from Napoleon Home %s — waiting for advertisement", self._mac)
        if not self._stopping and not self._circuit_open:
            self._register_bt_callback()

    # GATT notification routing

    @callback
    def _on_notification(self, sender: Any, raw: bytearray) -> None:
        """
        Process a raw GATT indication from the outbox characteristic.

        Feeds the raw bytes through the fragmentation assembler and, once a
        complete message is available, routes it by opcode:

        - ``oac t:1``: Schedules the HMAC response task (must not block callback).
        - ``oac t:2``: Sets the ``_auth_ok`` event to unblock ``_authenticate``.
        - ``gpr``: Applies the polled property value and pushes state to entities.
        - ``Odp``: Applies the pushed property value, ACKs with ``odp``, pushes state.
        - ``opr``: Logged as debug; either an ignored write-ACK or config-sync request.
        - ``ukn``: Logged as a warning; indicates the grill received an invalid command.

        Args:
            sender: The GATT characteristic that sent the indication (unused).
            raw: Raw bytes from the indication.

        """
        LOGGER.debug(
            "Napoleon Home %s: RX %d bytes: %s",
            self._mac,
            len(raw),
            raw.hex(),
        )
        complete = self._assembler.feed(bytes(raw))
        if complete is None:
            LOGGER.debug("Napoleon Home %s: RX fragment — awaiting more chunks", self._mac)
            return

        msg = decode_msg(complete)
        if msg is None:
            LOGGER.debug(
                "Napoleon Home %s: RX non-JSON data: %s",
                self._mac,
                complete.hex(),
            )
            return

        LOGGER.debug("Napoleon Home %s: RX msg: %s", self._mac, msg)
        opcode = msg.get("o")
        seq: int = msg.get("i", 0)
        payload: dict[str, Any] = msg.get("p") or {}

        if opcode == "oac":
            t = payload.get("t")
            if t == 1:
                s = payload.get("s")
                if s == BLE_AUTH_STATUS_NOT_PROVISIONED:
                    LOGGER.warning(
                        "Napoleon Home %s: grill not provisioned (s:6) — provision via Napoleon app first",
                        self._mac,
                    )
                    # Not a key error: don't set _auth_rejected. _authenticate will time out
                    # and the coordinator will retry on the next BLE advertisement.
                    return
                challenge = payload.get("c", "")
                LOGGER.debug(
                    "Napoleon Home %s: auth challenge received (oac t:1), sending HMAC response",
                    self._mac,
                )
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._send_hmac_response(challenge),
                    f"napoleon_home_auth_response_{self._mac}",
                )
            elif t == 2:
                s = payload.get("s")
                if s == BLE_AUTH_STATUS_REJECTED:
                    self._auth_rejected.set()
                else:
                    LOGGER.debug("Napoleon Home %s: auth accepted by grill (oac t:2)", self._mac)
                    self._auth_ok.set()
            else:
                LOGGER.debug("Napoleon Home %s: unexpected oac t=%s", self._mac, t)
        elif opcode == "gpr":
            name = payload.get("n")
            value = payload.get("v")
            if name is not None and value is not None:
                LOGGER.debug("Napoleon Home %s: gpr %s=%r", self._mac, name, value)
                self.data.update_from_property(name, value)
                self.async_set_updated_data(self.data)
        elif opcode == "Odp":
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
        elif opcode == "opr":
            LOGGER.debug("Napoleon Home %s: opr ack (n=%s)", self._mac, payload.get("n"))
        elif opcode == "ukn":
            LOGGER.warning(
                "Napoleon Home %s: ukn — invalid command rejected by grill (s=%s)",
                self._mac,
                msg.get("s"),
            )
        else:
            LOGGER.debug("Napoleon Home %s: unhandled opcode '%s'", self._mac, opcode)

    # GATT write helpers

    async def _send_hmac_response(self, challenge_b64: str) -> None:
        """
        Compute the HMAC-SHA256 response and send ``Oac t:2`` to the grill.

        Scheduled as a background task from the notification callback to avoid
        blocking the BLE event loop.

        Args:
            challenge_b64: The base64-encoded 32-byte nonce from the grill's
                ``oac t:1`` challenge message.

        """
        response = compute_hmac(self._local_key, challenge_b64)
        LOGGER.debug(
            "Napoleon Home %s: HMAC response computed (challenge=%s, response=%s)",
            self._mac,
            challenge_b64,
            response,
        )
        await self._send_msg("Oac", {"t": 2, "r": response})

    async def _send_msg(
        self,
        opcode: str,
        payload: dict[str, Any] | None = None,
        *,
        ack_seq: int | None = None,
    ) -> None:
        """
        Encode and write a protocol message to the inbox characteristic.

        Manages the per-session sequence counter and serialises all writes through
        an ``asyncio.Lock`` to prevent chunk interleaving when multiple coroutines
        write concurrently (e.g. polling and ACK responses overlapping).

        Long payloads are automatically fragmented by ``encode_inbox`` per the Ayla
        fragmentation protocol.

        Args:
            opcode: The Ayla protocol opcode string (e.g. ``"Oac"``, ``"Gpr"``).
            payload: Optional payload dict to include in the message envelope.
            ack_seq: When set, use this sequence number verbatim (for ``odp`` ACK
                replies that must echo the received message's ``i`` value). When
                None, the coordinator's internal counter is auto-incremented.

        """
        if self._client is None:
            LOGGER.debug(
                "Napoleon Home %s: _send_msg(%s) called while disconnected — dropped",
                self._mac,
                opcode,
            )
            return
        if ack_seq is not None:
            seq = ack_seq
        else:
            self._seq += 1
            seq = self._seq
        msg = make_msg(opcode, payload, seq)
        chunks = encode_inbox(msg, self._mtu)
        LOGGER.debug(
            "Napoleon Home %s: TX %s seq=%d (%d chunk(s), MTU=%d)",
            self._mac,
            opcode,
            seq,
            len(chunks),
            self._mtu,
        )
        async with self._write_lock:
            if self._client is None:
                return
            # Snapshot to a local variable; self._client can be nulled by the
            # exception handler in _connect_and_run between chunk iterations.
            ble_client = self._client
            for chunk in chunks:
                await ble_client.write_gatt_char(INBOX_UUID, chunk, response=True)

    async def _poll_properties(self) -> None:
        """
        Send a ``Gpr`` poll request for every property in ``POLL_PROPS``.

        Called by ``_async_update_data`` on each coordinator refresh cycle.
        Required when the grill has active WiFi/MQTT, since the grill only
        pushes ``Odp`` for state-change events (not temperatures) in that mode.
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

        Cancels any pending advertisement callback and disconnects the BLE client.
        Sets ``_stopping`` before disconnecting so that ``_on_disconnect`` does not
        re-register the advertisement callback after the entry is unloaded.

        Called from ``NapoleonHomeDataUpdateCoordinator.async_shutdown``.
        """
        LOGGER.debug("Napoleon Home %s: shutting down BLE", self._mac)
        self._stopping = True
        if self._bt_cancel_callback is not None:
            self._bt_cancel_callback()
            self._bt_cancel_callback = None
        if self._client is not None:
            await self._client.disconnect()
