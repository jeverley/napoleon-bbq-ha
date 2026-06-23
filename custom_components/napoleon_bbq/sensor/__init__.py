"""Sensor platform for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .diagnostic import ENTITY_DESCRIPTIONS as DIAGNOSTIC_DESCRIPTIONS, NapoleonBBQDiagnosticSensor
from .probe_temp import ENTITY_DESCRIPTIONS as PROBE_TEMP_DESCRIPTIONS, NapoleonBBQProbeTempSensor

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.data import NapoleonBBQConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonBBQConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    for subentry_id, coordinator in entry.runtime_data.items():
        async_add_entities(
            (
                NapoleonBBQProbeTempSensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in PROBE_TEMP_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
        async_add_entities(
            (
                NapoleonBBQDiagnosticSensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in DIAGNOSTIC_DESCRIPTIONS
            ),
            config_subentry_id=subentry_id,
        )
