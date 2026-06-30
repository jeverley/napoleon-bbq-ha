"""Light platform for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .knob_lights import ENTITY_DESCRIPTIONS as KNOB_LIGHTS_DESCRIPTIONS, NapoleonHomeBacklightLight

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light platform."""
    for coordinator in entry.runtime_data.values():
        async_add_entities(
            (
                NapoleonHomeBacklightLight(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in KNOB_LIGHTS_DESCRIPTIONS
            ),
        )
