"""LCD off switch for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_bbq.const import PROP_LCD_OFF, PROP_TYPE_BOOL
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator


ENTITY_DESCRIPTIONS: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="lcd_off",
        translation_key="lcd_off",
        icon="mdi:lightbulb-off",
        entity_category=None,
    ),
)


class NapoleonBBQLcdOffSwitch(SwitchEntity, NapoleonBBQEntity):
    """
    Switch controlling the knob backlight state on the Napoleon Prestige grill.

    When ``is_on`` is ``True``, the knob backlights are off (``LCD_OFF = 1``).
    Turning the switch on disables the backlights; turning it off re-enables them.

    """

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: SwitchEntityDescription,
    ) -> None:
        """
        Initialise the LCD off switch.

        Args:
            coordinator: The BLE coordinator managing grill state.
            entity_description: The entity description for this switch.

        """
        super().__init__(coordinator, entity_description)

    @property
    def is_on(self) -> bool:
        """Return True when the knob backlights are off."""
        return self.coordinator.data.lcd_off

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the backlights off (set LCD_OFF = 1)."""
        await self.coordinator.async_set_property(PROP_LCD_OFF, PROP_TYPE_BOOL, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the backlights on (set LCD_OFF = 0)."""
        await self.coordinator.async_set_property(PROP_LCD_OFF, PROP_TYPE_BOOL, 0)
