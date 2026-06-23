"""Knob backlight brightness select for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PROP_BRT_LVL, PROP_TYPE_INT
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator

_OPTIONS: dict[int, str] = {0: "low", 1: "medium", 2: "high"}
_OPTIONS_INV: dict[str, int] = {v: k for k, v in _OPTIONS.items()}

ENTITY_DESCRIPTIONS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="brightness",
        translation_key="brightness",
        icon="mdi:brightness-6",
        entity_category=EntityCategory.CONFIG,
    ),
)


class NapoleonBBQBrightnessSelect(SelectEntity, NapoleonBBQEntity):
    """Select controlling the knob backlight brightness level."""

    _attr_options = list(_OPTIONS.values())

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: SelectEntityDescription,
    ) -> None:
        """Initialise the brightness select."""
        super().__init__(coordinator, entity_description)

    @property
    def current_option(self) -> str | None:
        """Return the current brightness level option, or None if not yet received."""
        brt = self.coordinator.data.brt_lvl
        if brt is None:
            return None
        return _OPTIONS.get(brt)

    async def async_select_option(self, option: str) -> None:
        """Set the knob backlight brightness level on the grill."""
        await self.coordinator.async_set_property(PROP_BRT_LVL, PROP_TYPE_INT, _OPTIONS_INV[option])
