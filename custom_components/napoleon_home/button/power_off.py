"""Turn off button for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PROP_TOFF, PROP_TYPE_BOOL
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator


ENTITY_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="power_off",
        translation_key="power_off",
        icon="mdi:power",
    ),
)


class NapoleonHomePowerOffButton(ButtonEntity, NapoleonHomeEntity):
    """Button that sends the power-off command to the Napoleon Prestige grill."""

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: ButtonEntityDescription,
    ) -> None:
        """Initialise the power off button."""
        super().__init__(coordinator, entity_description)

    async def async_press(self) -> None:
        """Send the TOFF command to power off the grill."""
        await self.coordinator.async_set_property(PROP_TOFF, PROP_TYPE_BOOL, 1)
