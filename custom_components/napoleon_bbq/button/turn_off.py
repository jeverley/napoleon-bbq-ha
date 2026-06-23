"""Turn off button for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PROP_TOFF, PROP_TYPE_BOOL
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator


ENTITY_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="turn_off",
        translation_key="turn_off",
        icon="mdi:power",
    ),
)


class NapoleonBBQTurnOffButton(ButtonEntity, NapoleonBBQEntity):
    """Button that sends the turn-off command to the Napoleon Prestige grill."""

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: ButtonEntityDescription,
    ) -> None:
        """Initialise the turn off button."""
        super().__init__(coordinator, entity_description)

    async def async_press(self) -> None:
        """Send the TOFF command to power off the grill."""
        await self.coordinator.async_set_property(PROP_TOFF, PROP_TYPE_BOOL, 1)
