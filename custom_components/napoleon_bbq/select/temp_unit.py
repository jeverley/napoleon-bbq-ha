"""Temperature unit select for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PROP_TUNIT, PROP_TYPE_INT
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator

_OPTIONS: dict[int, str] = {0: "celsius", 1: "fahrenheit"}
_OPTIONS_INV: dict[str, int] = {v: k for k, v in _OPTIONS.items()}

ENTITY_DESCRIPTIONS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="temp_unit",
        translation_key="temp_unit",
        icon="mdi:thermometer",
        entity_category=EntityCategory.CONFIG,
    ),
)


class NapoleonBBQTempUnitSelect(SelectEntity, NapoleonBBQEntity):
    """Select controlling the grill's temperature unit (Celsius / Fahrenheit)."""

    _attr_options = list(_OPTIONS.values())

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: SelectEntityDescription,
    ) -> None:
        """Initialise the temperature unit select."""
        super().__init__(coordinator, entity_description)

    @property
    def current_option(self) -> str | None:
        """Return the currently selected temperature unit option."""
        return _OPTIONS.get(self.coordinator.data.tunit)

    async def async_select_option(self, option: str) -> None:
        """Set the temperature unit on the grill."""
        await self.coordinator.async_set_property(PROP_TUNIT, PROP_TYPE_INT, _OPTIONS_INV[option])
