"""Number platform for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PARALLEL_UPDATES as PARALLEL_UPDATES

from .automatic_shutoff import ENTITY_DESCRIPTIONS as AUTO_SHUTOFF_DESCRIPTIONS, NapoleonHomeAutoShutoffNumber
from .tank_calibration import ENTITY_DESCRIPTIONS as TANK_CALIBRATION_DESCRIPTIONS, NapoleonHomeTankCalibrationNumber
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
    for coordinator in entry.runtime_data.values():
        async_add_entities(
            (
                NapoleonHomeAutoShutoffNumber(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in AUTO_SHUTOFF_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeTargetTempNumber(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in ENTITY_DESCRIPTIONS
            ),
        )
        async_add_entities(
            (
                NapoleonHomeTankCalibrationNumber(
                    coordinator=coordinator,
                    entity_description=entity_description,
                )
                for entity_description in TANK_CALIBRATION_DESCRIPTIONS
            ),
        )
