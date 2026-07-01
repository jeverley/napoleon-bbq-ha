"""Custom integration to integrate napoleon_home with Home Assistant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from homeassistant.components.bluetooth import async_rediscover_address
from homeassistant.const import Platform
import homeassistant.helpers.config_validation as cv

from .const import CONF_DEVICES, DOMAIN
from .coordinator import NapoleonHomeDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceEntry

    from .data import NapoleonHomeConfigEntry, NapoleonHomeCoordinators

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> bool:
    """Set up Napoleon Home from a config entry."""
    coordinators: NapoleonHomeCoordinators = {
        mac: NapoleonHomeDataUpdateCoordinator(hass, entry, mac) for mac in entry.data.get(CONF_DEVICES, {})
    }
    entry.runtime_data = coordinators
    await asyncio.gather(*(c.async_config_entry_first_refresh() for c in coordinators.values()))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    for coordinator in entry.runtime_data.values():
        await coordinator.async_shutdown()
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Remove a grill device and its data when deleted from the UI."""
    mac = next(
        (identifier for domain, identifier in device_entry.identifiers if domain == DOMAIN),
        None,
    )
    if mac is None:
        return False
    devices = entry.data.get(CONF_DEVICES, {})
    if mac not in devices:
        return True
    coordinator = entry.runtime_data.pop(mac, None)
    if coordinator is not None:
        await coordinator.async_shutdown()
    hass.config_entries.async_update_entry(
        entry,
        data={**entry.data, CONF_DEVICES: {m: d for m, d in devices.items() if m != mac}},
    )
    async_rediscover_address(hass, mac)
    return True


async def async_reload_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
