"""Custom integration to integrate napoleon_bbq with Home Assistant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from homeassistant.const import Platform
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, SUBENTRY_TYPE_DEVICE
from .coordinator import NapoleonBBQDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import NapoleonBBQConfigEntry, NapoleonBBQCoordinators

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
) -> bool:
    """Set up Napoleon BBQ from a config entry."""
    coordinators: NapoleonBBQCoordinators = {
        subentry_id: NapoleonBBQDataUpdateCoordinator(hass, entry, subentry)
        for subentry_id, subentry in entry.subentries.items()
        if subentry.subentry_type == SUBENTRY_TYPE_DEVICE
    }
    entry.runtime_data = coordinators
    await asyncio.gather(*(c.async_config_entry_first_refresh() for c in coordinators.values()))
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    for coordinator in entry.runtime_data.values():
        await coordinator.async_shutdown()
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
