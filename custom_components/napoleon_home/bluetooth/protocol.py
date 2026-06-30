"""
Ayla BLE Local Control v2 protocol helpers for napoleon_home.

This module provides stateless encode/decode helpers for the Ayla IoT BLE
Local Control v2 protocol used by the Napoleon Prestige grill. These helpers
serve the same role as an external BLE library would in other integrations —
all BLE protocol logic is isolated here so the coordinator can remain focused
on connection management and state.

All protocol traffic flows over two GATT characteristics:
- Inbox  (01000001-fe28): app → grill, written in fragments when needed.
- Outbox (01000002-fe28): grill → app, received as GATT indications.

Message envelope (both directions):
    {"o": "<opcode>", "i": <seq>, "p": {<payload>}}

The sequence number is managed by the coordinator as a per-session instance
counter. All functions in this module are stateless.

For more information on the Ayla BLE protocol:
See _handover/CLAUDE.md — Protocol section.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


def make_msg(opcode: str, payload: dict[str, Any] | None = None, seq: int = 0) -> str:
    """Encode an Ayla protocol message as a compact JSON string.

    Args:
        opcode: The Ayla opcode string (e.g. "Oac", "Gpr", "Opr").
        payload: Optional payload dict. Omitted from the envelope when None.
        seq: Message sequence number managed by the coordinator.

    Returns:
        A compact JSON string ready to write to the inbox characteristic.

    """
    msg: dict[str, Any] = {"o": opcode, "i": seq}
    if payload is not None:
        msg["p"] = payload
    return json.dumps(msg, separators=(",", ":"))


def decode_msg(raw: bytes) -> dict[str, Any] | None:
    """Decode a raw outbox indication into a protocol message dict.

    Args:
        raw: Raw bytes from a single outbox characteristic indication.

    Returns:
        Parsed message dict, or None if the bytes are not valid UTF-8 JSON.

    """
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def encode_inbox(payload: str, mtu: int = 512) -> list[bytes]:
    """Split a payload string into ATT write chunks per AylaMessageFragmenter.

    Short payloads that fit within a single ATT write are returned as-is.
    Longer payloads are split into fragments, each prefixed with a 4-character
    hex offset. The MSB of the offset is set on the final fragment to signal
    end-of-message.

    All GATT writes must use response=True (write-with-response). Concurrent
    callers must be serialised with an asyncio.Lock to avoid interleaving chunks.

    Args:
        payload: The JSON string to encode.
        mtu: The negotiated MTU size for the current connection.

    Returns:
        A list of byte chunks to write sequentially to the inbox characteristic.

    """
    prefix_len = 4
    msb_flag = 0x8000
    chunk_size = mtu - 3 - prefix_len

    if len(payload) <= mtu - 3:
        return [payload.encode("utf-8")]

    chunks: list[bytes] = []
    offset = 0
    data = payload.encode("utf-8")
    while offset < len(data):
        segment = data[offset : offset + chunk_size]
        is_last = (offset + len(segment)) >= len(data)
        prefix_val = offset | (msb_flag if is_last else 0)
        chunks.append(f"{prefix_val:04x}".encode() + segment)
        offset += len(segment)
    return chunks


def compute_hmac(local_key: str, challenge_b64: str) -> str:
    """Compute the HMAC-SHA256 auth response for the Ayla local-control handshake.

    The grill issues a base64-encoded nonce in the oac t:1 challenge. The response is:
        HMAC-SHA256(key=local_key.encode("utf-8"), msg=b"response" + base64.b64decode(challenge_b64))

    Args:
        local_key: Per-device key string from the Ayla cloud API (used as UTF-8, not decoded).
        challenge_b64: Base64-encoded nonce from the grill's oac t:1 challenge.

    Returns:
        Base64-encoded HMAC-SHA256 digest to send as the oac t:2 auth response.

    """
    key = local_key.encode("utf-8")
    data = b"response" + base64.b64decode(challenge_b64)
    digest = hmac.new(key, data, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class NapoleonHomeOutboxAssembler:
    """Reassemble fragmented outbox indications into complete messages.

    Outbox messages starting with '{' are passed through immediately as
    unfragmented. All other chunks carry a 4-character hex offset prefix and
    are buffered until the final fragment (MSB set on offset) arrives.

    """

    def __init__(self) -> None:
        """Initialise the assembler with an empty reassembly buffer."""
        self._buf: bytearray = bytearray()

    def reset(self) -> None:
        """Clear the reassembly buffer for a new connection."""
        self._buf = bytearray()

    def feed(self, data: bytes) -> bytes | None:
        """Feed a raw indication chunk and return the complete message when ready.

        Args:
            data: Raw bytes from a single outbox indication.

        Returns:
            The complete reassembled message bytes when the final fragment is
            received, or None if more fragments are still expected.

        """
        prefix_len = 4
        msb_flag = 0x8000

        # Unfragmented: device messages always begin with '{'.
        if data and data[0] == ord("{"):
            self._buf = bytearray()
            return data

        if len(data) < prefix_len:
            return None

        prefix_hex = data[:prefix_len].decode("ascii", errors="replace")
        try:
            prefix_val = int(prefix_hex, 16)
        except ValueError:
            return None

        chunk = data[prefix_len:]
        is_last = bool(prefix_val & msb_flag)

        if prefix_val & ~msb_flag == 0:
            self._buf = bytearray(chunk)
        else:
            self._buf.extend(chunk)

        if is_last:
            result = bytes(self._buf)
            self._buf = bytearray()
            return result

        return None
