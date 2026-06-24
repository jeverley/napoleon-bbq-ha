"""Knob backlight light entity for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_home.const import PROP_BRT_LVL, PROP_LCD_OFF, PROP_TYPE_BOOL, PROP_TYPE_INT
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity, LightEntityDescription
from homeassistant.components.light.const import ColorMode

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

# Grill brightness levels (BRT_LVL) mapped to HA brightness (0-255)
_BRT_TO_HA: dict[int, int] = {0: 85, 1: 170, 2: 255}


def _ha_to_brt(ha_brightness: int) -> int:
    """Map HA brightness (0-255) to the nearest grill BRT_LVL (0=low, 1=medium, 2=high)."""
    return round(ha_brightness * 2 / 255)


ENTITY_DESCRIPTIONS: tuple[LightEntityDescription, ...] = (
    LightEntityDescription(
        key="backlight",
        translation_key="backlight",
    ),
)


class NapoleonHomeBacklightLight(LightEntity, NapoleonHomeEntity):
    """Light entity for the knob backlights on the Napoleon Prestige grill.

    On/off maps to LCD_OFF (0 = on, 1 = off). Brightness maps to BRT_LVL
    (0 = low → 85, 1 = medium → 170, 2 = high → 255).

    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

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

    @property
    def brightness(self) -> int | None:
        """Return the current brightness mapped from BRT_LVL, or None if not yet received."""
        brt = self.coordinator.data.brt_lvl
        if brt is None:
            return None
        return _BRT_TO_HA.get(brt, 255)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the backlights on, optionally setting brightness."""
        await self.coordinator.async_set_property(PROP_LCD_OFF, PROP_TYPE_BOOL, 0)
        if ATTR_BRIGHTNESS in kwargs:
            brt = _ha_to_brt(kwargs[ATTR_BRIGHTNESS])
            await self.coordinator.async_set_property(PROP_BRT_LVL, PROP_TYPE_INT, brt)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the backlights off (LCD_OFF = 1)."""
        await self.coordinator.async_set_property(PROP_LCD_OFF, PROP_TYPE_BOOL, 1)
