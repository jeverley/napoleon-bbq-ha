"""Diagnostics support for napoleon_home."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.redact import async_redact_data

from .const import CONF_LOCAL_KEY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import NapoleonHomeConfigEntry

TO_REDACT: set[str] = {CONF_LOCAL_KEY}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    grills: dict[str, Any] = {}
    for mac, coordinator in entry.runtime_data.items():
        grills[mac] = {
            "device": async_redact_data(coordinator.device_data, TO_REDACT),
            "coordinator": {
                "connected": coordinator.connected,
                "authenticated": coordinator.authenticated,
                "last_update_success": coordinator.last_update_success,
                "update_interval": str(coordinator.update_interval),
                "last_exception": str(coordinator.last_exception) if coordinator.last_exception else None,
            },
            "grill_state": asdict(coordinator.data) if coordinator.data else None,
        }

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "grills": grills,
    }
