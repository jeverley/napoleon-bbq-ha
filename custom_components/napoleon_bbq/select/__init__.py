"""Select platform for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .brightness import ENTITY_DESCRIPTIONS as BRIGHTNESS_DESCRIPTIONS, NapoleonBBQBrightnessSelect
from .gas_unit import ENTITY_DESCRIPTIONS as GAS_UNIT_DESCRIPTIONS, NapoleonBBQGasUnitSelect
from .temp_unit import ENTITY_DESCRIPTIONS as TEMP_UNIT_DESCRIPTIONS, NapoleonBBQTempUnitSelect

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.data import NapoleonBBQConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select platform."""
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            (
                NapoleonBBQTempUnitSelect(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in TEMP_UNIT_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
        async_add_entities(
            (
                NapoleonBBQBrightnessSelect(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in BRIGHTNESS_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
        async_add_entities(
            (
                NapoleonBBQGasUnitSelect(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in GAS_UNIT_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
