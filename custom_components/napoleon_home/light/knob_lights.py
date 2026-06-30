"""Knob backlight light entity for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_home.const import PROP_LCD_OFF, PROP_TYPE_BOOL
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.light import LightEntity, LightEntityDescription
from homeassistant.components.light.const import ColorMode

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

ENTITY_DESCRIPTIONS: tuple[LightEntityDescription, ...] = (
    LightEntityDescription(
        key="knob_lights",
        translation_key="knob_lights",
        icon="mdi:knob",
    ),
)


class NapoleonHomeBacklightLight(LightEntity, NapoleonHomeEntity):
    """Light entity for the knob backlights on the Napoleon Prestige grill.

    On/off maps to LCD_OFF (0 = on, 1 = off). Display brightness is a
    separate select entity (BRT_LVL).

    """

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: LightEntityDescription,
    ) -> None:
        """Initialise the backlight light."""
        super().__init__(coordinator, entity_description)

    @property
    def is_on(self) -> bool:
        """Return True when the knob backlights are on (LCD_OFF = 0)."""
        return not self.coordinator.data.lcd_off

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the backlights on."""
        await self.coordinator.async_set_property(PROP_LCD_OFF, PROP_TYPE_BOOL, 0)
        self.coordinator.data.lcd_off = False
        self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the backlights off (LCD_OFF = 1)."""
        await self.coordinator.async_set_property(PROP_LCD_OFF, PROP_TYPE_BOOL, 1)
        self.coordinator.data.lcd_off = True
        self.coordinator.async_set_updated_data(self.coordinator.data)
