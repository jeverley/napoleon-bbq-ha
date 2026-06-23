"""Diagnostics support for napoleon_bbq."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.redact import async_redact_data

from .const import CONF_LOCAL_KEY, SUBENTRY_TYPE_DEVICE

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import NapoleonBBQConfigEntry

TO_REDACT: set[str] = {CONF_LOCAL_KEY}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    grills: dict[str, Any] = {}
    for subentry_id, coordinator in entry.runtime_data.items():
        subentry = coordinator.subentry
        grills[subentry_id] = {
            "subentry": {
                "title": subentry.title,
                "data": async_redact_data(dict(subentry.data), TO_REDACT),
            },
            "coordinator": {
                "connected": coordinator.connected,
                "authenticated": coordinator.authenticated,
                "last_update_success": coordinator.last_update_success,
                "update_interval": str(coordinator.update_interval),
                "last_exception": str(coordinator.last_exception) if coordinator.last_exception else None,
            },
            "grill_state": asdict(coordinator.data) if coordinator.data else None,
        }

    unconfigured_subentries = [
        {"subentry_id": sid, "title": sub.title, "subentry_type": sub.subentry_type}
        for sid, sub in entry.subentries.items()
        if sub.subentry_type != SUBENTRY_TYPE_DEVICE
    ]

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "grills": grills,
        **({"unconfigured_subentries": unconfigured_subentries} if unconfigured_subentries else {}),
    }
