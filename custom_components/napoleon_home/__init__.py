"""Custom integration to integrate napoleon_home with Home Assistant."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
import homeassistant.helpers.config_validation as cv

from .const import CONF_DEVICES, CONF_DSN, CONF_LOCAL_KEY, CONF_LOCAL_KEY_ID, CONF_MAC, DOMAIN
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

# Only used in async_migrate_entry to identify v1 device subentries
_SUBENTRY_TYPE_DEVICE = "device"

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
    for mac in entry.data.get(CONF_DEVICES, {}):
        for platform, key in _REMOVED_ENTITY_KEYS:
            entity_id = entity_reg.async_get_entity_id(platform, DOMAIN, f"{mac}_{key}")
            if entity_id:
                entity_reg.async_remove(entity_id)


async def async_migrate_entry(hass: HomeAssistant, entry: NapoleonHomeConfigEntry) -> bool:
    """Migrate old config entry versions to the current schema."""
    if entry.version == 1:
        # v1 → v3: flatten subentries into entry.data[CONF_DEVICES] keyed by uppercase MAC.
        devices: dict[str, Any] = {}
        device_subentry_ids: list[str] = []
        for subentry in list(entry.subentries.values()):
            if subentry.subentry_type != _SUBENTRY_TYPE_DEVICE:
                continue
            mac = subentry.data[CONF_MAC].upper()
            devices[mac] = {
                CONF_DSN: subentry.data.get(CONF_DSN, ""),
                CONF_LOCAL_KEY: subentry.data.get(CONF_LOCAL_KEY, ""),
                CONF_LOCAL_KEY_ID: subentry.data.get(CONF_LOCAL_KEY_ID, 0),
                "name": subentry.title,
            }
            device_subentry_ids.append(subentry.subentry_id)
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_DEVICES: devices},
            version=3,
            minor_version=1,
        )
        for subentry_id in device_subentry_ids:
            hass.config_entries.async_remove_subentry(entry, subentry_id)
    elif entry.version == 2:
        # v2 → v3: uppercase CONF_DEVICES keys (were stored lowercase in v2).
        devices_v2 = entry.data.get(CONF_DEVICES, {})
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_DEVICES: {mac.upper(): data for mac, data in devices_v2.items()}},
            version=3,
            minor_version=1,
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> bool:
    """Set up Napoleon Home from a config entry."""
    _remove_stale_entities(hass, entry)
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


async def async_reload_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> None:
    """Reload config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
