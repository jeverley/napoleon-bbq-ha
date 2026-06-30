"""Repair flows for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class NapoleonHomeRepairFlow(RepairsFlow):
    """Close the BLE circuit on the affected coordinator after the user resolves the error."""

    def __init__(self, entry_id: str, mac: str, issue_id: str) -> None:  # noqa: D107
        self._entry_id = entry_id
        self._mac = mac
        self._issue_id = issue_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:  # noqa: D102
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> data_entry_flow.FlowResult:  # noqa: D102
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self._entry_id)
            if entry is not None:
                coordinator = getattr(entry, "runtime_data", {}).get(self._mac)
                if coordinator is not None:
                    coordinator.async_close_circuit()
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm")


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the repair flow for a BLE circuit-breaker issue."""
    assert data is not None
    return NapoleonHomeRepairFlow(str(data["entry_id"]), str(data["mac"]), issue_id)


__all__ = ["NapoleonHomeRepairFlow", "async_create_fix_flow"]
