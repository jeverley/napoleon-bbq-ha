"""Custom integration to integrate napoleon_home with Home Assistant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv

from .const import CONF_MAC, DOMAIN, SUBENTRY_TYPE_DEVICE
from .coordinator import NapoleonHomeDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

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


_REMOVED_ENTITY_KEYS: tuple[tuple[str, str], ...] = (
    # lcd_off switch and brightness select replaced by the backlight light entity
    ("switch", "lcd_off"),
    ("select", "brightness"),
    # battery_saver renamed to display_idle_timeout
    ("switch", "battery_saver"),
    # display_power_save switch migrated to diagnostic sensor
    ("switch", "display_power_save"),
    # display_power_save diagnostic sensor migrated to binary_sensor
    ("sensor", "display_power_save"),
    # connected binary sensor renamed to connectivity, then to status
    ("binary_sensor", "connected"),
    ("binary_sensor", "connectivity"),
    # turn_off button renamed to power_off
    ("button", "turn_off"),
    # renamed keys to match current naming
    ("binary_sensor", "display_power_save"),
    ("sensor", "battery_level"),
    ("sensor", "probe_4_temp"),
    ("sensor", "firmware_version"),
    ("light", "backlight"),
    ("select", "temp_unit"),
    ("select", "gas_unit"),
    ("number", "auto_shutoff"),
    ("sensor", "probe_1_temp"),
    ("sensor", "probe_2_temp"),
    ("sensor", "probe_3_temp"),
    ("sensor", "grill_temperature"),
    ("number", "probe_1_target_temp"),
    ("number", "probe_2_target_temp"),
    ("number", "probe_3_target_temp"),
    ("number", "probe_4_target_temp"),
    ("number", "probe_4_target"),
)


def _remove_stale_entities(hass: HomeAssistant, entry: NapoleonHomeConfigEntry) -> None:
    """Remove entity registry entries that no longer exist in this version."""
    entity_reg = er.async_get(hass)
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_DEVICE:
            continue
        mac = subentry.data[CONF_MAC].lower()
        for platform, key in _REMOVED_ENTITY_KEYS:
            entity_id = entity_reg.async_get_entity_id(platform, DOMAIN, f"{mac}_{key}")
            if entity_id:
                entity_reg.async_remove(entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> bool:
    """Set up Napoleon Home from a config entry."""
    _remove_stale_entities(hass, entry)
    coordinators: NapoleonHomeCoordinators = {
        subentry_id: NapoleonHomeDataUpdateCoordinator(hass, entry, subentry)
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
    entry: NapoleonHomeConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    for coordinator in entry.runtime_data.values():
        await coordinator.async_shutdown()
    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
