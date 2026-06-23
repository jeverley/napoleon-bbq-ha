"""Battery saver switch for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_bbq.const import PROP_BSMODE, PROP_TYPE_BOOL
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator


ENTITY_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="battery_saver",
        translation_key="battery_saver",
        icon="mdi:battery-saver",
    ),
)


class NapoleonBBQBatterySaverSwitch(SwitchEntity, NapoleonBBQEntity):
    """Switch controlling battery/screen saver mode on the Napoleon Prestige grill."""

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """Initialise the battery saver switch."""
        super().__init__(coordinator, entity_description)

    @property
    def is_on(self) -> bool:
        """Return True when battery saver mode is active."""
        return self.coordinator.data.bsmode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable battery saver mode (BSMODE = 1)."""
        await self.coordinator.async_set_property(PROP_BSMODE, PROP_TYPE_BOOL, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable battery saver mode (BSMODE = 0)."""
        await self.coordinator.async_set_property(PROP_BSMODE, PROP_TYPE_BOOL, 0)
