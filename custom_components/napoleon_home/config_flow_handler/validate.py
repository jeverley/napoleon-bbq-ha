"""BLE key validation for the napoleon_home config flow."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from custom_components.napoleon_home.bluetooth import NapoleonHomeOutboxAssembler, compute_hmac, encode_inbox, make_msg
from custom_components.napoleon_home.const import (
    AUTH_TIMEOUT,
    AUTH_USER,
    BLE_AUTH_STATUS_NOT_PROVISIONED,
    BLE_AUTH_STATUS_REJECTED,
    INBOX_UUID,
    LOGGER,
    OUTBOX_UUID,
)
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_NOT_PROVISIONED = "not_provisioned"


class NapoleonHomeNotProvisionedError(HomeAssistantError):
    """Raised when the grill responds s:6 — not provisioned via Napoleon app yet."""


class NapoleonHomeAlreadyBondedError(HomeAssistantError):
    """Raised when the grill rejects writes with ATT 0x05 (Insufficient Authentication).

    A provisioned grill disables new BLE bonding after it has been set up via the
    Napoleon app. The grill must be factory-reset to re-enable bonding, after which
    it must be provisioned again before the local key is available.
    """


def _is_att_insufficient_auth(err: Exception) -> bool:
    """Return True if the exception is an ATT Insufficient Authentication error (0x05)."""
    msg = str(err).lower()
    return "0x05" in msg or "insufficient authentication" in msg or "insufficient auth" in msg


def _raise_key_rejected(mac: str) -> None:
    msg = f"Napoleon Home {mac}: local key rejected by grill (s:4)"
    raise ConfigEntryAuthFailed(msg)


def _raise_not_provisioned(mac: str) -> None:
    msg = f"Napoleon Home {mac}: grill not provisioned (s:6) — complete setup in Napoleon app first"
    raise NapoleonHomeNotProvisionedError(msg)


def _raise_already_bonded(mac: str) -> None:
    msg = f"Napoleon Home {mac}: grill rejected write (ATT 0x05) — new BLE bonding disabled after provisioning; factory reset required"
    raise NapoleonHomeAlreadyBondedError(msg)


async def async_check_ble_provisioned(hass: HomeAssistant, mac: str) -> bool:
    """
    Probe the grill to determine whether it has been provisioned via the Napoleon app.

    Connects, sends an ``Oac t:1`` challenge request, and inspects the response:
    - ``oac t:1 c:<challenge>`` → provisioned (returns ``True``)
    - ``oac t:1 s:6`` → not provisioned (returns ``False``)
    - ATT error 0x05 on write → grill is provisioned but new bonding is disabled (raises
      ``NapoleonHomeAlreadyBondedError``; factory reset required)
    - Timeout or other connection failure → returns ``True`` (unknown state;
      let the normal flow handle it)

    As a side effect, the BLE connection establishes a bond (pairing) with the grill —
    this must happen before the user provisions via the Napoleon app, since provisioning
    disables new bonding.

    Args:
        hass: The Home Assistant instance.
        mac: BLE MAC address of the grill (e.g. ``"AA:BB:CC:DD:EE:FF"``).

    Returns:
        ``False`` if the grill is definitely not provisioned (``s:6``), ``True`` otherwise.

    Raises:
        NapoleonHomeAlreadyBondedError: If the grill rejects the write with ATT 0x05,
            indicating it is provisioned and no longer accepts new BLE bonds.

    """
    ble_device = async_ble_device_from_address(hass, mac, connectable=True)
    if ble_device is None:
        return True  # Can't reach grill — let normal flow handle it

    result_queue: asyncio.Queue[bool] = asyncio.Queue(maxsize=1)
    assembler = NapoleonHomeOutboxAssembler()
    client: BleakClientWithServiceCache | None = None

    def _on_notification(sender: object, raw: bytearray) -> None:
        complete = assembler.feed(bytes(raw))
        if complete is None:
            return
        try:
            msg_data: dict = json.loads(complete)
        except ValueError, TypeError:
            return
        if msg_data.get("o") == "oac":
            payload: dict = msg_data.get("p") or {}
            if payload.get("t") == 1:
                provisioned = payload.get("s") != BLE_AUTH_STATUS_NOT_PROVISIONED
                hass.async_create_task(result_queue.put(provisioned), eager_start=True)

    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            mac,
            disconnected_callback=lambda _: None,
            max_attempts=1,
        )
        await client.start_notify(OUTBOX_UUID, _on_notification)
        init_msg = make_msg("Oac", {"t": 1, "i": AUTH_USER}, 1)
        try:
            for chunk in encode_inbox(init_msg):
                await client.write_gatt_char(INBOX_UUID, chunk, response=True)
        except Exception as write_err:  # noqa: BLE001
            if _is_att_insufficient_auth(write_err):
                LOGGER.warning("Napoleon Home %s: ATT 0x05 — grill is bonded to another device", mac)
                _raise_already_bonded(mac)
            return True  # Other write failure — fall through to normal flow

        try:
            return await asyncio.wait_for(result_queue.get(), timeout=AUTH_TIMEOUT)
        except TimeoutError:
            return True  # Unknown — fall through to normal flow

    except NapoleonHomeAlreadyBondedError:
        raise
    except Exception:  # noqa: BLE001
        return True  # Connection failure — let normal flow surface the error
    finally:
        if client is not None:
            try:
                await client.disconnect()
                LOGGER.debug("Napoleon Home %s: setup_stage=validate_disconnect mode=provision_check result=done", mac)
            except Exception:  # noqa: BLE001
                LOGGER.debug("Napoleon Home %s: setup_stage=validate_disconnect mode=provision_check result=error", mac)
        else:
            LOGGER.debug("Napoleon Home %s: setup_stage=validate_disconnect mode=provision_check result=skipped", mac)


async def async_validate_ble_key(hass: HomeAssistant, mac: str, local_key: str) -> None:
    """
    Validate a BLE local key by completing the Ayla Local Control v2 auth handshake.

    Connects to the grill, sends ``Oac t:1``, computes the HMAC response on
    the received challenge, and waits for the grill's ``oac t:2`` reply.
    The connection is always closed in the finally block.

    Args:
        hass: The Home Assistant instance.
        mac: BLE MAC address of the grill (e.g. ``"AA:BB:CC:DD:EE:FF"``).
        local_key: Base64-encoded BLE authentication key to validate.

    Raises:
        NapoleonHomeAlreadyBondedError: If the grill rejects the write with ATT 0x05,
            indicating it is provisioned and no longer accepts new BLE bonds.
        NapoleonHomeNotProvisionedError: If the grill responds with ``s:6`` on ``oac t:1``
            (not provisioned via Napoleon app yet).
        ConfigEntryAuthFailed: If the grill rejects the HMAC response (``oac t:2 s:4``).
        HomeAssistantError: If the grill is not found, the connection fails,
            or authentication times out.

    """
    ble_device = async_ble_device_from_address(hass, mac, connectable=True)
    if ble_device is None:
        msg = f"Napoleon Home {mac}: grill not found via Bluetooth"
        raise HomeAssistantError(msg)

    result_queue: asyncio.Queue[bool | str] = asyncio.Queue(maxsize=1)
    assembler = NapoleonHomeOutboxAssembler()
    seq = 0

    client: BleakClientWithServiceCache | None = None

    def _on_notification(sender: object, raw: bytearray) -> None:
        complete = assembler.feed(bytes(raw))
        if complete is None:
            return
        try:
            msg_data: dict = json.loads(complete)
        except ValueError, TypeError:
            return
        op = msg_data.get("o")
        payload: dict = msg_data.get("p") or {}
        if op == "oac":
            t = payload.get("t")
            if t == 1:
                if payload.get("s") == BLE_AUTH_STATUS_NOT_PROVISIONED:
                    hass.async_create_task(result_queue.put(_NOT_PROVISIONED), eager_start=True)
                    return
                challenge: str = payload.get("c", "")
                response = compute_hmac(local_key, challenge)
                out = make_msg("Oac", {"t": 2, "r": response}, seq + 1)
                chunks = encode_inbox(out)
                if client is not None:
                    _cli = client

                    async def _send_response(_c: BleakClientWithServiceCache = _cli) -> None:
                        for chunk in chunks:
                            await _c.write_gatt_char(INBOX_UUID, chunk, response=True)

                    hass.async_create_task(_send_response(), eager_start=True)
            elif t == 2:
                s = payload.get("s")
                accepted = s != BLE_AUTH_STATUS_REJECTED
                hass.async_create_task(result_queue.put(accepted), eager_start=True)

    try:
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            mac,
            disconnected_callback=lambda _: None,
            max_attempts=1,
        )
        await client.start_notify(OUTBOX_UUID, _on_notification)
        seq = 1
        init_msg = make_msg("Oac", {"t": 1, "i": AUTH_USER}, seq)
        try:
            for chunk in encode_inbox(init_msg):
                await client.write_gatt_char(INBOX_UUID, chunk, response=True)
        except Exception as write_err:
            if _is_att_insufficient_auth(write_err):
                LOGGER.warning("Napoleon Home %s: ATT 0x05 — grill is bonded to another device", mac)
                _raise_already_bonded(mac)
            msg = f"Napoleon Home {mac}: BLE write failed — {write_err}"
            raise HomeAssistantError(msg) from write_err

        try:
            result = await asyncio.wait_for(result_queue.get(), timeout=AUTH_TIMEOUT)
        except TimeoutError as err:
            msg = f"Napoleon Home {mac}: BLE authentication timed out during key validation"
            raise HomeAssistantError(msg) from err

        if result == _NOT_PROVISIONED:
            LOGGER.warning("Napoleon Home %s: BLE key validation — grill not provisioned (s:6)", mac)
            _raise_not_provisioned(mac)
        elif not result:
            LOGGER.warning("Napoleon Home %s: BLE key validation rejected (s:4)", mac)
            _raise_key_rejected(mac)

    except NapoleonHomeAlreadyBondedError, NapoleonHomeNotProvisionedError, ConfigEntryAuthFailed, HomeAssistantError:
        raise
    except Exception as err:
        msg = f"Napoleon Home {mac}: BLE connection failed during key validation — {err}"
        raise HomeAssistantError(msg) from err
    finally:
        if client is not None:
            try:
                await client.disconnect()
                LOGGER.debug("Napoleon Home %s: setup_stage=validate_disconnect mode=key_validation result=done", mac)
            except Exception:  # noqa: BLE001
                LOGGER.debug("Napoleon Home %s: setup_stage=validate_disconnect mode=key_validation result=error", mac)
        else:
            LOGGER.debug("Napoleon Home %s: setup_stage=validate_disconnect mode=key_validation result=skipped", mac)
