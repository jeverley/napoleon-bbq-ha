"""Sensor platform for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .battery import ENTITY_DESCRIPTIONS as BATTERY_DESCRIPTIONS, NapoleonHomeBatterySensor
from .firmware import ENTITY_DESCRIPTIONS as FIRMWARE_DESCRIPTIONS, NapoleonHomeFirmwareVersionSensor
from .probe_temp import ENTITY_DESCRIPTIONS as PROBE_TEMP_DESCRIPTIONS, NapoleonHomeProbeTempSensor
from .tank_weight import (
    DEBUG_ENTITY_DESCRIPTIONS as TANK_DEBUG_DESCRIPTIONS,
    ENTITY_DESCRIPTIONS as TANK_WEIGHT_DESCRIPTIONS,
    NapoleonHomeTankDebugSensor,
    NapoleonHomeTankWeightSensor,
)

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NapoleonHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    for coordinator in entry.runtime_data.values():
        async_add_entities(
            (
                NapoleonHomeProbeTempSensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in PROBE_TEMP_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeBatterySensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in BATTERY_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeFirmwareVersionSensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in FIRMWARE_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeTankWeightSensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in TANK_WEIGHT_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeTankDebugSensor(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in TANK_DEBUG_DESCRIPTIONS
            ),
        )
