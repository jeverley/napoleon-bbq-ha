"""
BLE connection lifecycle mixin for napoleon_bbq.

Separates the BLE connection management, authentication handshake, and GATT
notification handling from the DataUpdateCoordinator polling logic. Mixed into
``NapoleonBBQDataUpdateCoordinator`` in ``base.py``.

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
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from custom_components.napoleon_bbq.bluetooth import (
    NapoleonBBQOutboxAssembler,
    compute_hmac,
    decode_msg,
    encode_inbox,
    make_msg,
)
from custom_components.napoleon_bbq.const import (
    AUTH_TIMEOUT,
    AUTH_USER,
    ENCRYPT_SETTLE,
    INBOX_UUID,
    LOGGER,
    MAX_CONNECT_FAILURES,
    OUTBOX_UUID,
    POLL_PROPS,
)
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
)
from homeassistant.core import CALLBACK_TYPE, callback

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.data import NapoleonBBQConfigEntry, NapoleonBBQGrillState
    from homeassistant.core import HomeAssistant


class NapoleonBBQBLEMixin:
    """
    BLE connection lifecycle mixin for the Napoleon Prestige grill coordinator.

    Provides advertisement detection, BLE connection with retry, Ayla Local Control
    v2 HMAC authentication, fragmented GATT write helpers, and notification routing.

    Requires the host class to provide:
        - ``self.hass`` (HomeAssistant)
        - ``self.config_entry`` (NapoleonBBQConfigEntry)
        - ``self.data`` (NapoleonBBQGrillState)
        - ``self.async_set_updated_data(data)``

    Initialise BLE state by calling ``_init_ble(mac, local_key)`` from ``__init__``.

    """

    if TYPE_CHECKING:
        hass: HomeAssistant
        config_entry: NapoleonBBQConfigEntry
        data: NapoleonBBQGrillState
        update_interval: timedelta | None
        _poll_interval: int

        def async_set_updated_data(self, data: NapoleonBBQGrillState) -> None:  # noqa: D102
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
        self._assembler = NapoleonBBQOutboxAssembler()
        self._write_lock = asyncio.Lock()
        self._auth_ok = asyncio.Event()
        self._seq: int = 0
        self._connecting: bool = False
        self._connect_failures: int = 0
        self._bt_cancel_callback: CALLBACK_TYPE | None = None
        self._stopping: bool = False
        self._circuit_open: bool = False

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
        LOGGER.debug("Napoleon BBQ %s: waiting for advertisement", self._mac)
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
        if self._bt_cancel_callback is not None:
            self._bt_cancel_callback()
            self._bt_cancel_callback = None
        if self._connecting or self.connected:
            # A connection is already in progress or established. Discard this
            # advertisement — _connect_and_run will re-register the callback when
            # the current attempt concludes.
            LOGGER.debug(
                "Napoleon BBQ %s: advertisement ignored — already %s",
                self._mac,
                "connecting" if self._connecting else "connected",
            )
            return
        LOGGER.debug(
            "Napoleon BBQ %s: advertisement received (rssi=%s), connecting",
            self._mac,
            service_info.advertisement.rssi,
        )
        self.config_entry.async_create_background_task(
            self.hass,
            self._connect_and_run(service_info.device),
            f"napoleon_bbq_connect_{self._mac}",
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
                "Napoleon BBQ %s: BLE connect (failure_count=%d/%d)",
                self._mac,
                self._connect_failures,
                MAX_CONNECT_FAILURES,
            )
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
            if self._stopping:
                # Shutdown raced the connect; disconnect cleanly and exit without
                # incrementing the failure counter.
                with contextlib.suppress(Exception):
                    await client.disconnect()
                return
            LOGGER.debug("Napoleon BBQ %s: BLE connected, subscribing to outbox", self._mac)
            self._seq = 0
            self._assembler = NapoleonBBQOutboxAssembler()
            # Assign self._client before sleeping so _shutdown_ble can disconnect us
            # if it races this window, and so immediate Odp ACKs from start_notify
            # can be sent via _send_msg.
            self._client = client
            await asyncio.sleep(ENCRYPT_SETTLE)
            await client.start_notify(OUTBOX_UUID, self._on_notification)
            self._mtu = client.mtu_size
            LOGGER.debug("Napoleon BBQ %s: outbox subscribed (MTU=%d)", self._mac, self._mtu)
            await self._authenticate()
        except Exception:  # noqa: BLE001
            self._connect_failures += 1
            if self._connect_failures >= MAX_CONNECT_FAILURES:
                LOGGER.error(
                    "Napoleon BBQ %s: %d consecutive connection failures — stopping auto-reconnect; "
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
                LOGGER.exception("Error connecting to Napoleon BBQ %s", self._mac)
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
        LOGGER.debug("Napoleon BBQ %s: sending auth challenge request (Oac t:1)", self._mac)
        await self._send_msg("Oac", {"t": 1, "i": AUTH_USER})
        try:
            await asyncio.wait_for(self._auth_ok.wait(), timeout=AUTH_TIMEOUT)
            self._connect_failures = 0
            LOGGER.debug("Napoleon BBQ %s: authenticated", self._mac)
            self.update_interval = timedelta(seconds=self._poll_interval)
            self.config_entry.async_create_background_task(
                self.hass,
                self.async_refresh(),
                f"napoleon_bbq_initial_poll_{self._mac}",
            )
        except TimeoutError:
            LOGGER.warning("Authentication timed out for Napoleon BBQ %s", self._mac)
            # Re-raise so _connect_and_run's except block counts this as a failure.
            # _connect_and_run then disconnects the client explicitly.
            raise

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
        self.update_interval = None
        LOGGER.debug("Disconnected from Napoleon BBQ %s — waiting for advertisement", self._mac)
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
        complete = self._assembler.feed(bytes(raw))
        if complete is None:
            return

        msg = decode_msg(complete)
        if msg is None:
            LOGGER.debug("Received non-JSON outbox data from Napoleon BBQ %s", self._mac)
            return

        opcode = msg.get("o")
        seq: int = msg.get("i", 0)
        payload: dict[str, Any] = msg.get("p") or {}

        if opcode == "oac":
            t = payload.get("t")
            if t == 1:
                challenge = payload.get("c", "")
                LOGGER.debug(
                    "Napoleon BBQ %s: auth challenge received (oac t:1), sending HMAC response",
                    self._mac,
                )
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._send_hmac_response(challenge),
                    f"napoleon_bbq_auth_response_{self._mac}",
                )
            elif t == 2:
                LOGGER.debug("Napoleon BBQ %s: auth accepted by grill (oac t:2)", self._mac)
                self._auth_ok.set()
            else:
                LOGGER.debug("Napoleon BBQ %s: unexpected oac t=%s", self._mac, t)
        elif opcode == "gpr":
            name = payload.get("n")
            value = payload.get("v")
            if name is not None and value is not None:
                LOGGER.debug("Napoleon BBQ %s: gpr %s=%r", self._mac, name, value)
                self.data.update_from_property(name, value)
                self.async_set_updated_data(self.data)
        elif opcode == "Odp":
            name = payload.get("n")
            value = payload.get("v")
            if name is not None and value is not None:
                LOGGER.debug("Napoleon BBQ %s: push %s=%r (seq=%d)", self._mac, name, value, seq)
                self.data.update_from_property(name, value)
                self.async_set_updated_data(self.data)
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._send_msg("odp", {"n": name}, ack_seq=seq),
                    f"napoleon_bbq_odp_ack_{self._mac}",
                )
        elif opcode == "opr":
            LOGGER.debug("Napoleon BBQ %s: opr ack (n=%s)", self._mac, payload.get("n"))
        elif opcode == "ukn":
            LOGGER.warning(
                "Napoleon BBQ %s: ukn — invalid command rejected by grill (s=%s)",
                self._mac,
                msg.get("s"),
            )
        else:
            LOGGER.debug("Napoleon BBQ %s: unhandled opcode '%s'", self._mac, opcode)

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
                "Napoleon BBQ %s: _send_msg(%s) called while disconnected — dropped",
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
            "Napoleon BBQ %s: TX %s seq=%d (%d chunk(s), MTU=%d)",
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

    async def _shutdown_ble(self) -> None:
        """
        Tear down BLE state cleanly.

        Cancels any pending advertisement callback and disconnects the BLE client.
        Sets ``_stopping`` before disconnecting so that ``_on_disconnect`` does not
        re-register the advertisement callback after the entry is unloaded.

        Called from ``NapoleonBBQDataUpdateCoordinator.async_shutdown``.
        """
        LOGGER.debug("Napoleon BBQ %s: shutting down BLE", self._mac)
        self._stopping = True
        if self._bt_cancel_callback is not None:
            self._bt_cancel_callback()
            self._bt_cancel_callback = None
        if self._client is not None:
            await self._client.disconnect()
