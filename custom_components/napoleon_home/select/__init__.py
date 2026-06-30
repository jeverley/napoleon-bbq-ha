"""Select platform for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .brightness import ENTITY_DESCRIPTIONS as BRIGHTNESS_DESCRIPTIONS, NapoleonHomeDisplayBrightnessSelect
from .tank_unit import ENTITY_DESCRIPTIONS as GAS_UNIT_DESCRIPTIONS, NapoleonHomeGasUnitSelect
from .temperature_unit import ENTITY_DESCRIPTIONS as TEMP_UNIT_DESCRIPTIONS, NapoleonHomeTempUnitSelect

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the select platform."""
    for coordinator in entry.runtime_data.values():
        async_add_entities(
            (
                NapoleonHomeTempUnitSelect(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in TEMP_UNIT_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeDisplayBrightnessSelect(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in BRIGHTNESS_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeGasUnitSelect(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in GAS_UNIT_DESCRIPTIONS
            ),
        )
