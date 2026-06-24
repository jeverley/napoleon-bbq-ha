"""Display power save switch for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_bbq.const import PROP_BSMODE, PROP_TYPE_BOOL
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator


ENTITY_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="display_power_save",
        translation_key="display_power_save",
        icon="mdi:timer-outline",
        entity_category=EntityCategory.CONFIG,
    ),
)


class NapoleonBBQDisplayPowerSaveSwitch(SwitchEntity, NapoleonBBQEntity):
    """Switch enabling or disabling display power save on the Napoleon Prestige grill.

    When on, the display automatically turns off after the configured AUTO_T_OUT period
    of inactivity (BSMODE = 1). When off, the display stays on indefinitely (BSMODE = 0).

    """

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """Initialise the display power save switch."""
        super().__init__(coordinator, entity_description)

    @property
    def is_on(self) -> bool:
        """Return True when display power save is enabled (BSMODE = 1)."""
        return self.coordinator.data.bsmode

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable display power save (BSMODE = 1)."""
        await self.coordinator.async_set_property(PROP_BSMODE, PROP_TYPE_BOOL, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable display power save (BSMODE = 0)."""
        await self.coordinator.async_set_property(PROP_BSMODE, PROP_TYPE_BOOL, 0)
