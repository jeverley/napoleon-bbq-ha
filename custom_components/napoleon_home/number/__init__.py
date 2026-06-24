"""Number platform for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .target_temp import ENTITY_DESCRIPTIONS, NapoleonHomeTargetTempNumber

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the number platform."""
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            (
                NapoleonHomeTargetTempNumber(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in ENTITY_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
