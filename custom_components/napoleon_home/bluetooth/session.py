"""
NapoleonHomeBLESession — shared BLE session for napoleon_home.

Owns one BLE connection lifecycle and implements the Ayla Local Control v2
protocol operations (auth handshake, provisioning probe, GATT write helpers).

Used by both the coordinator (long-lived, replaced on each reconnect) and the
config flow (short-lived context manager), replacing independent BLE
implementations in listeners.py and validate.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
import contextlib
from typing import Any, Self

from bleak.backends.device import BLEDevice
from bleak.exc import BleakDBusError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from custom_components.napoleon_home.bluetooth.errors import (
    NapoleonHomeAlreadyBondedError,
    NapoleonHomeNotProvisionedError,
)
from custom_components.napoleon_home.bluetooth.protocol import (
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
    DISPLAY_NAME_UUID,
    DOMAIN,
    DSN_UUID,
    GATT_DEVICE_NAME_UUID,
    INBOX_UUID,
    LOGGER,
    OUTBOX_UUID,
)
from homeassistant.exceptions import ConfigEntryAuthFailed

_AUTH_NOT_PROVISIONED = "not_provisioned"
_AUTH_REJECTED = "rejected"
_AUTH_ACCEPTED = "accepted"


_BLUEZ_PAIRING_REJECTED = frozenset(
    {
        "org.bluez.Error.AuthenticationFailed",
        "org.bluez.Error.AuthenticationRejected",
    }
)


def _is_pairing_rejected(err: Exception) -> bool:
    return isinstance(err, BleakDBusError) and err.dbus_error in _BLUEZ_PAIRING_REJECTED


def _is_att_insufficient_auth(err: Exception) -> bool:
    return (
        isinstance(err, BleakDBusError)
        and err.dbus_error == "org.bluez.Error.Failed"
        and (err.dbus_error_details or "").startswith("ATT error: 0x05")
    )


class NapoleonHomeBLESession:
    """
    Single-connection BLE session for a Napoleon Prestige grill.

    Owns connection lifecycle (connect → pair → MTU → disconnect) and provides
    an opcode-keyed notification handler registry so multiple consumers can
    receive GATT indications from a single Bleak callback.

    Implements the Ayla Local Control v2 operations:
    - ``check_provisioned()``: fire ``Oac t:1``, detect ``s:6`` vs challenge.
    - ``authenticate(local_key)``: full HMAC handshake.
    - ``write_msg()``: encode and write to the inbox characteristic.

    Usage (config flow — short-lived)::

        async with NapoleonHomeBLESession(mac) as session:
            await session.connect(ble_device)
            provisioned = await session.check_provisioned()

    Usage (coordinator — long-lived)::

        session = NapoleonHomeBLESession(mac)
        await session.connect(device, on_disconnect=self._on_disconnect, ...)
        session.register_handler("gpr", self._handle_gpr)
        session.register_handler("Odp", self._handle_odp)
        await session.authenticate(self._local_key)
        # ... session remains open for polling ...
        await session.disconnect()

    """

    def __init__(self, mac: str) -> None:
        """Initialise session state. No BLE connection is made here."""
        self._mac = mac
        self._client: BleakClientWithServiceCache | None = None
        self._mtu: int = 512
        self._assembler: NapoleonHomeOutboxAssembler = NapoleonHomeOutboxAssembler()
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._seq: int = 0
        self._handlers: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._dsn: str | None = None
        self._display_name: str | None = None
        self._model: str | None = None

    # ── Public properties ────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """Return True if the underlying BleakClient is currently connected."""
        return self._client is not None and self._client.is_connected

    @property
    def mtu(self) -> int:
        """Return the negotiated MTU size for this connection."""
        return self._mtu

    @property
    def dsn(self) -> str | None:
        """DSN read from the GATT DUID characteristic after bonding, or None."""
        return self._dsn

    @property
    def display_name(self) -> str | None:
        """User-configurable alias from DISPLAY_NAME_UUID, or None."""
        return self._display_name

    @property
    def model(self) -> str | None:
        """Device model string from Generic Access Device Name (0x2A00), or None."""
        return self._model

    # ── Notification dispatch ────────────────────────────────────────────────

    def register_handler(self, opcode: str, fn: Callable[[dict[str, Any]], None]) -> None:
        """Register a notification callback for the given protocol opcode."""
        self._handlers.setdefault(opcode, []).append(fn)

    def unregister_handler(self, opcode: str, fn: Callable[[dict[str, Any]], None]) -> None:
        """Remove a previously registered notification callback."""
        with contextlib.suppress(ValueError):
            self._handlers.get(opcode, []).remove(fn)

    def _on_bleak_notification(self, sender: Any, raw: bytearray) -> None:
        """Internal Bleak notification callback — assembles fragments and dispatches."""
        LOGGER.debug("Napoleon Home %s: RX %d bytes: %s", self._mac, len(raw), raw.hex())
        complete = self._assembler.feed(bytes(raw))
        if complete is None:
            LOGGER.debug("Napoleon Home %s: RX fragment — awaiting more chunks", self._mac)
            return

        msg = decode_msg(complete)
        if msg is None:
            LOGGER.debug("Napoleon Home %s: RX non-JSON data: %s", self._mac, complete.hex())
            return

        LOGGER.debug("Napoleon Home %s: RX msg: %s", self._mac, msg)
        opcode: str | None = msg.get("o")
        if not opcode:
            return
        for handler in list(self._handlers.get(opcode, [])):
            handler(msg)

    # ── Connection lifecycle ─────────────────────────────────────────────────

    async def connect(
        self,
        ble_device: BLEDevice,
        *,
        on_disconnect: Callable[..., None] | None = None,
        ble_device_callback: Callable[[], BLEDevice] | None = None,
    ) -> None:
        """
        Establish BLE connection, pair, subscribe to outbox, and negotiate MTU.

        Args:
            ble_device: The BLE device to connect to.
            on_disconnect: Optional callback invoked by BleakClient on disconnect.
            ble_device_callback: Optional callable returning a fresh BLEDevice for
                the ``ble_device_callback`` parameter of ``establish_connection``.

        Raises:
            BleakNotFoundError: Device not found.
            TimeoutError: Connection attempt timed out.
            Exception: Any other Bleak-level error.

        """
        self._seq = 0
        self._assembler = NapoleonHomeOutboxAssembler()

        self._client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self._mac,
            disconnected_callback=on_disconnect,
            max_attempts=1,
            ble_device_callback=ble_device_callback,
        )

        LOGGER.debug("Napoleon Home %s: BLE connected, reading open characteristics", self._mac)

        # 0x2A00 (Generic Access Device Name) is readable without a bond — gives the
        # model string (e.g. "Prestige-1F2"). DSN and display name require encryption
        # so they are read after pair() below.
        self._model = await self._read_gatt_char_string(GATT_DEVICE_NAME_UUID, "model (0x2A00)")

        # Bond before any INBOX write — INBOX (01000001-fe28) requires an encrypted,
        # bonded link. On first run this triggers Just Works SMP; on subsequent runs
        # BlueZ uses the stored LTK and pair() returns immediately.
        try:
            await self._client.pair()
            LOGGER.debug("Napoleon Home %s: BLE link bonded/encrypted", self._mac)
        except Exception as err:
            if _is_pairing_rejected(err):
                LOGGER.debug(
                    "Napoleon Home %s: pair() rejected — grill bonded to another device: %s",
                    self._mac,
                    err,
                )
                raise NapoleonHomeAlreadyBondedError(
                    f"Napoleon Home {self._mac}: grill rejected pairing (bonded to another device)"
                ) from err
            LOGGER.debug("Napoleon Home %s: pair() raised — proceeding (already bonded?)", self._mac)

        # DSN and display name require an encrypted link — read after pair().
        self._dsn = await self._read_gatt_char_string(DSN_UUID, "DSN")
        self._display_name = await self._read_gatt_char_string(DISPLAY_NAME_UUID, "display name")

        try:
            await self._client.start_notify(OUTBOX_UUID, self._on_bleak_notification)
        except Exception as err:
            self._raise_if_bonded(err)
            raise

        # Negotiate a large MTU so the full Oac payload fits in one write.
        _acquire = getattr(getattr(self._client, "_backend", self._client), "_acquire_mtu", None)
        if callable(_acquire):
            await _acquire()  # type: ignore[misc]
            self._mtu = self._client.mtu_size

        LOGGER.debug("Napoleon Home %s: outbox subscribed (MTU=%d)", self._mac, self._mtu)

    async def read_open_characteristics(self, ble_device: BLEDevice) -> None:
        """Connect and read open GATT characteristics. Does not pair or subscribe.

        Only 0x2A00 (Generic Access Device Name) is readable without a bond.
        DSN and display name require encryption and are not read here.
        """
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self._mac,
            max_attempts=1,
        )
        LOGGER.debug("Napoleon Home %s: BLE connected, reading open characteristics", self._mac)
        self._model = await self._read_gatt_char_string(GATT_DEVICE_NAME_UUID, "model (0x2A00)")

    async def disconnect(self) -> None:
        """Disconnect from the grill (suppresses errors)."""
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.disconnect()
            self._client = None

    # ── Protocol operations ──────────────────────────────────────────────────

    async def write_msg(
        self,
        opcode: str,
        payload: dict[str, Any] | None = None,
        *,
        ack_seq: int | None = None,
    ) -> None:
        """
        Encode and write a protocol message to the inbox characteristic.

        Args:
            opcode: Ayla protocol opcode (e.g. ``"Oac"``, ``"Gpr"``, ``"Opr"``).
            payload: Optional payload dict included in the message envelope.
            ack_seq: When set, use this sequence number verbatim (for ``odp`` ACK
                replies that must echo the received message's ``i`` value).
                When None, auto-increment the session-local sequence counter.

        """
        if self._client is None:
            LOGGER.debug(
                "Napoleon Home %s: write_msg(%s) called while disconnected — dropped",
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
            ble_client = self._client
            for chunk in chunks:
                await ble_client.write_gatt_char(INBOX_UUID, chunk, response=True)

    async def check_provisioned(self) -> bool | None:
        """
        Probe whether the grill has been provisioned via the Napoleon app.

        Sends ``Oac t:1`` and inspects the grill's reply:

        - ``s:6`` at the top level of the ``oac`` response → ``False`` (not provisioned).
        - ``p.t == 1`` with a challenge field → ``True`` (provisioned, challenge ready).
        - ATT 0x05 (Insufficient Authentication) on write → raises
          ``NapoleonHomeAlreadyBondedError`` (grill bonded to another device; can't write).
        - Timeout or any other error → ``None`` (unknown; caller should not block setup).

        """
        result_queue: asyncio.Queue[bool] = asyncio.Queue(maxsize=1)

        def _oac_handler(msg: dict[str, Any]) -> None:
            if msg.get("s") == BLE_AUTH_STATUS_NOT_PROVISIONED:
                with contextlib.suppress(asyncio.QueueFull):
                    result_queue.put_nowait(False)
                return
            payload = msg.get("p") or {}
            if payload.get("t") == 1:
                with contextlib.suppress(asyncio.QueueFull):
                    result_queue.put_nowait(True)

        with self._oac_subscription(_oac_handler):
            try:
                await self.write_msg("Oac", {"t": 1, "i": AUTH_USER})
                return await asyncio.wait_for(result_queue.get(), timeout=AUTH_TIMEOUT)
            except TimeoutError:
                return None
            except Exception as err:  # noqa: BLE001
                self._raise_if_bonded(err)
                return None

    async def authenticate(self, local_key: str) -> None:
        """
        Perform the Ayla Local Control v2 HMAC-SHA256 authentication handshake.

        Sends ``Oac t:1`` (challenge request), waits for the grill's challenge on
        the outbox, computes the HMAC-SHA256 response, sends ``Oac t:2``, and
        waits for the grill's ``oac t:2`` reply indicating accept or reject.

        Raises:
            NapoleonHomeNotProvisionedError: Grill replies ``s:6`` (top-level) —
                grill has not been set up via the Napoleon app yet.
            NapoleonHomeAlreadyBondedError: Grill refuses writes with ATT 0x05 —
                bonded to another device; factory reset required.
            ConfigEntryAuthFailed: Grill rejects the HMAC response (``s:4`` on
                ``oac t:2``) — local key has rotated; trigger reauthentication.
            TimeoutError: No response within ``AUTH_TIMEOUT``.

        """
        auth_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=4)

        def _oac_handler(msg: dict[str, Any]) -> None:
            # Not-provisioned response: s:6 at top level, no p field.
            if msg.get("s") == BLE_AUTH_STATUS_NOT_PROVISIONED:
                with contextlib.suppress(asyncio.QueueFull):
                    auth_queue.put_nowait(_AUTH_NOT_PROVISIONED)
                return
            payload = msg.get("p") or {}
            t = payload.get("t")
            if t == 1:
                challenge = payload.get("c", "")
                with contextlib.suppress(asyncio.QueueFull):
                    auth_queue.put_nowait(f"challenge:{challenge}")
            elif t == 2:
                s = payload.get("s")
                token = _AUTH_REJECTED if s == BLE_AUTH_STATUS_REJECTED else _AUTH_ACCEPTED
                with contextlib.suppress(asyncio.QueueFull):
                    auth_queue.put_nowait(token)

        with self._oac_subscription(_oac_handler):
            try:
                LOGGER.debug("Napoleon Home %s: sending auth challenge request (Oac t:1)", self._mac)
                await self.write_msg("Oac", {"t": 1, "i": AUTH_USER})

                first = await asyncio.wait_for(auth_queue.get(), timeout=AUTH_TIMEOUT)

                if first == _AUTH_NOT_PROVISIONED:
                    msg_text = (
                        f"Napoleon Home {self._mac}: grill not provisioned (s:6) — provision via Napoleon app first"
                    )
                    LOGGER.warning(msg_text)
                    raise NapoleonHomeNotProvisionedError(msg_text)  # noqa: TRY301

                if first == _AUTH_REJECTED:
                    LOGGER.warning("Napoleon Home %s: BLE auth rejected (s:4) — local key has rotated", self._mac)
                    raise ConfigEntryAuthFailed(  # noqa: TRY301
                        translation_domain=DOMAIN,
                        translation_key="ble_auth_rejected",
                    )

                if first == _AUTH_ACCEPTED:
                    LOGGER.debug("Napoleon Home %s: authenticated (direct accept)", self._mac)
                    return

                if first.startswith("challenge:"):
                    challenge = first[len("challenge:") :]
                    response = compute_hmac(local_key, challenge)
                    LOGGER.debug(
                        "Napoleon Home %s: auth challenge received, sending HMAC response",
                        self._mac,
                    )
                    await self.write_msg("Oac", {"t": 2, "r": response})
                    second = await asyncio.wait_for(auth_queue.get(), timeout=AUTH_TIMEOUT)
                    if second == _AUTH_REJECTED:
                        LOGGER.warning("Napoleon Home %s: BLE auth rejected (s:4) — local key has rotated", self._mac)
                        raise ConfigEntryAuthFailed(  # noqa: TRY301
                            translation_domain=DOMAIN,
                            translation_key="ble_auth_rejected",
                        )
                    LOGGER.debug("Napoleon Home %s: authenticated", self._mac)
                    return

                LOGGER.debug("Napoleon Home %s: unexpected auth message: %s", self._mac, first)
                raise RuntimeError(f"Napoleon Home {self._mac}: unexpected auth message — {first!r}")  # noqa: TRY301

            except NapoleonHomeNotProvisionedError, NapoleonHomeAlreadyBondedError, ConfigEntryAuthFailed, TimeoutError:
                raise
            except Exception as err:
                self._raise_if_bonded(err)
                LOGGER.debug("Napoleon Home %s: BLE auth error: %s", self._mac, err)
                raise

    @contextlib.contextmanager
    def _oac_subscription(self, handler: Callable[[dict[str, Any]], None]) -> Iterator[None]:
        """Register an oac handler for the duration of the context, then unregister."""
        self.register_handler("oac", handler)
        try:
            yield
        finally:
            self.unregister_handler("oac", handler)

    def _raise_if_bonded(self, err: Exception) -> None:
        """Raise NapoleonHomeAlreadyBondedError if err is an ATT Insufficient Authentication error."""
        if _is_att_insufficient_auth(err):
            raise NapoleonHomeAlreadyBondedError(f"Napoleon Home {self._mac}: grill refuses bond (ATT 0x05)") from err

    async def _read_gatt_char_string(self, uuid: str, label: str) -> str | None:
        """Read a UTF-8 GATT characteristic, strip nulls/whitespace, and return the value or None."""
        if self._client is None:
            return None
        try:
            data = await asyncio.wait_for(self._client.read_gatt_char(uuid), timeout=5.0)
        except Exception as err:  # noqa: BLE001
            LOGGER.debug("Napoleon Home %s: %s read failed: %s", self._mac, label, err)
            return None
        try:
            result = data.decode("utf-8").strip("\x00").strip() or None
        except UnicodeDecodeError:
            return None
        LOGGER.debug("Napoleon Home %s: %s=%s", self._mac, label, result or "(empty)")
        return result

    async def read_dsn(self) -> str | None:
        """Read DSN from the GATT DUID characteristic. Requires a bonded/encrypted link."""
        return await self._read_gatt_char_string(DSN_UUID, "DSN")

    async def read_display_name(self) -> str | None:
        """Read the user-configurable alias from the GATT display name characteristic.

        Requires a bonded/encrypted link. Returns None on failure.
        """
        return await self._read_gatt_char_string(DISPLAY_NAME_UUID, "display name")

    # ── Context manager ──────────────────────────────────────────────────────

    async def __aenter__(self) -> Self:
        """Return self for use as an async context manager."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Disconnect when leaving the context."""
        await self.disconnect()
