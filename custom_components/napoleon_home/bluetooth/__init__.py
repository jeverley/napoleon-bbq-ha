"""
Bluetooth package for napoleon_home.

This package contains the Ayla BLE Local Control v2 protocol helpers used
to communicate with the Napoleon Prestige grill over Bluetooth LE.

Architecture:
    Three-layer data flow: Entities → Coordinator → Bluetooth Protocol.
    Only the coordinator should use these helpers. Entities must never
    import from this package directly.

For more information on the Ayla BLE protocol:
See _handover/CLAUDE.md — Protocol section.
"""

from .errors import NapoleonHomeAlreadyBondedError, NapoleonHomeNotProvisionedError
from .protocol import NapoleonHomeOutboxAssembler, compute_hmac, decode_msg, encode_inbox, make_msg
from .session import NapoleonHomeBLESession

__all__ = [
    "NapoleonHomeAlreadyBondedError",
    "NapoleonHomeBLESession",
    "NapoleonHomeNotProvisionedError",
    "NapoleonHomeOutboxAssembler",
    "compute_hmac",
    "decode_msg",
    "encode_inbox",
    "make_msg",
]
