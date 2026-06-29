"""Temperature unit select for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PROP_TUNIT, PROP_TYPE_INT
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

_OPTIONS: dict[int, str] = {0: "celsius", 1: "fahrenheit"}
_OPTIONS_INV: dict[str, int] = {v: k for k, v in _OPTIONS.items()}

ENTITY_DESCRIPTIONS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="temperature_unit",
        translation_key="temperature_unit",
        icon="mdi:thermometer",
        entity_category=EntityCategory.CONFIG,
    ),
)


class NapoleonHomeTempUnitSelect(SelectEntity, NapoleonHomeEntity):
    """Select controlling the grill's temperature unit (Celsius / Fahrenheit)."""

    _attr_options = list(_OPTIONS.values())

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
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
        value = _OPTIONS_INV[option]
        await self.coordinator.async_set_property(PROP_TUNIT, PROP_TYPE_INT, value)
        self.coordinator.data.tunit = value
        self.coordinator.async_set_updated_data(self.coordinator.data)
