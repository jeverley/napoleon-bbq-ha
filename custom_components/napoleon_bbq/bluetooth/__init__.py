"""
Bluetooth package for napoleon_bbq.

This package contains the Ayla BLE Local Control v2 protocol helpers used
to communicate with the Napoleon Prestige grill over Bluetooth LE.

Architecture:
    Three-layer data flow: Entities → Coordinator → Bluetooth Protocol.
    Only the coordinator should use these helpers. Entities must never
    import from this package directly.

For more information on the Ayla BLE protocol:
See _handover/CLAUDE.md — Protocol section.
"""

from .protocol import NapoleonBBQOutboxAssembler, compute_hmac, decode_msg, encode_inbox, make_msg

__all__ = [
    "NapoleonBBQOutboxAssembler",
    "compute_hmac",
    "decode_msg",
    "encode_inbox",
    "make_msg",
]
