"""
Device info utility for napoleon_bbq.

Provides a single helper for building the ``DeviceInfo`` object used by all
entities in the integration. Centralising this ensures that the device
registry entry stays consistent across all platforms.

For more information on device info:
https://developers.home-assistant.io/docs/device_registry_index
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import CONF_DSN, CONF_MAC, DOMAIN, MANUFACTURER
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator


def build_device_info(coordinator: NapoleonBBQDataUpdateCoordinator) -> DeviceInfo:
    """
    Build the device registry entry for a Napoleon Prestige grill.

    Uses the grill MAC address as the stable device identifier so that
    the device registry entry persists across integration reinstalls.

    Args:
        coordinator: The BLE coordinator for this sub-entry. Provides access
            to the sub-entry data (MAC address, DSN) and title (grill name).

    Returns:
        A ``DeviceInfo`` instance suitable for setting on
        ``_attr_device_info`` in any entity class.

    """
    subentry = coordinator.subentry
    return DeviceInfo(
        identifiers={(DOMAIN, subentry.data[CONF_MAC])},
        name=subentry.title,
        manufacturer=MANUFACTURER,
        model="Prestige",
        serial_number=subentry.data.get(CONF_DSN),
    )
