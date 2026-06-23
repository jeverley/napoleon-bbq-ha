"""Switch platform for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .battery_saver import ENTITY_DESCRIPTIONS as BATTERY_SAVER_DESCRIPTIONS, NapoleonBBQBatterySaverSwitch
from .lcd_off import ENTITY_DESCRIPTIONS as LCD_OFF_DESCRIPTIONS, NapoleonBBQLcdOffSwitch

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.data import NapoleonBBQConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            (
                NapoleonBBQLcdOffSwitch(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in LCD_OFF_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
        async_add_entities(
            (
                NapoleonBBQBatterySaverSwitch(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in BATTERY_SAVER_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
