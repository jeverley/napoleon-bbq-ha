"""
Device info utility for napoleon_home.

Provides a single helper for building the ``DeviceInfo`` object used by all
entities in the integration. Centralising this ensures that the device
registry entry stays consistent across all platforms.

For more information on device info:
https://developers.home-assistant.io/docs/device_registry_index
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import CONF_DSN, DOMAIN, MANUFACTURER
from homeassistant.helpers.device_registry import DeviceInfo

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator


def build_device_info(coordinator: NapoleonHomeDataUpdateCoordinator) -> DeviceInfo:
    """
    Build the device registry entry for a Napoleon Prestige grill.

    Uses the grill MAC address as the stable device identifier so that
    the device registry entry persists across integration reinstalls.

    Args:
        coordinator: The BLE coordinator for this grill. Provides MAC address,
            device name, and DSN from the entry's device data dict.

    Returns:
        A ``DeviceInfo`` instance suitable for setting on
        ``_attr_device_info`` in any entity class.

    """
    device_data = coordinator.device_data
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.mac)},
        name=device_data["name"],
        manufacturer=MANUFACTURER,
        model="Prestige",
        serial_number=device_data.get(CONF_DSN),
    )
