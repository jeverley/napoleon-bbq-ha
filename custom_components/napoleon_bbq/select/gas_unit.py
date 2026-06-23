"""Gas unit select for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.const import PROP_GS_UNT, PROP_TYPE_INT
from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator

_OPTIONS: dict[int, str] = {0: "kg", 1: "lbs"}
_OPTIONS_INV: dict[str, int] = {v: k for k, v in _OPTIONS.items()}

ENTITY_DESCRIPTIONS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="gas_unit",
        translation_key="gas_unit",
        icon="mdi:propane-tank",
        entity_category=EntityCategory.CONFIG,
    ),
)


class NapoleonBBQGasUnitSelect(SelectEntity, NapoleonBBQEntity):
    """Select controlling the gas tank weight unit (kg / lbs)."""

    _attr_options = list(_OPTIONS.values())

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: SelectEntityDescription,
    ) -> None:
        """Initialise the gas unit select."""
        super().__init__(coordinator, entity_description)

    @property
    def current_option(self) -> str | None:
        """Return the current gas unit option."""
        return _OPTIONS.get(self.coordinator.data.gs_unt)

    async def async_select_option(self, option: str) -> None:
        """Set the gas tank weight unit on the grill."""
        await self.coordinator.async_set_property(PROP_GS_UNT, PROP_TYPE_INT, _OPTIONS_INV[option])
