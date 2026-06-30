"""Display brightness select for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PROP_BRT_LVL, PROP_TYPE_INT
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

# BRT_LVL grill values: 1=low, 3=mid, 5=high; 0 is an invalid residual value treated as low on read
_READ_OPTIONS: dict[int, str] = {0: "low", 1: "low", 3: "medium", 5: "high"}
_WRITE_OPTIONS: dict[str, int] = {"low": 1, "medium": 3, "high": 5}

ENTITY_DESCRIPTIONS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="display_brightness",
        translation_key="display_brightness",
        icon="mdi:brightness-6",
        entity_category=EntityCategory.CONFIG,
    ),
)


class NapoleonHomeDisplayBrightnessSelect(SelectEntity, NapoleonHomeEntity):
    """Select controlling the grill display brightness (BRT_LVL 1/3/5)."""

    _attr_options = list(_WRITE_OPTIONS.keys())

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: SelectEntityDescription,
    ) -> None:
        """Initialise the display brightness select."""
        super().__init__(coordinator, entity_description)

    @property
    def current_option(self) -> str | None:
        """Return the current display brightness option."""
        brt_lvl = self.coordinator.data.brt_lvl
        return _READ_OPTIONS.get(brt_lvl) if brt_lvl is not None else None

    async def async_select_option(self, option: str) -> None:
        """Set the display brightness on the grill."""
        value = _WRITE_OPTIONS[option]
        await self.coordinator.async_set_property(PROP_BRT_LVL, PROP_TYPE_INT, value)
        self.coordinator.data.brt_lvl = value
        self.coordinator.async_set_updated_data(self.coordinator.data)
