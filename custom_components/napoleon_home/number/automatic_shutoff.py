"""Auto-shutoff timeout number entity for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PROP_AUTO_T_OUT, PROP_TYPE_INT
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

ENTITY_DESCRIPTIONS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(
        key="automatic_shutoff",
        translation_key="automatic_shutoff",
        icon="mdi:timer-off-outline",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=1,
        native_max_value=24,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
    ),
)


class NapoleonHomeAutoShutoffNumber(NumberEntity, NapoleonHomeEntity):
    """Number entity for the grill auto-shutoff timeout (AUTO_T_OUT, 1–24 hours)."""

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: NumberEntityDescription,
    ) -> None:
        """Initialise the auto-shutoff number."""
        super().__init__(coordinator, entity_description)

    @property
    def native_value(self) -> float | None:
        """Return the current auto-shutoff timeout in hours, or None if not yet polled."""
        raw = self.coordinator.data.auto_t_out
        return round(raw / 60) if raw is not None else None

    async def async_set_native_value(self, value: float) -> None:
        """Set the auto-shutoff timeout on the grill."""
        minutes = int(value) * 60
        await self.coordinator.async_set_property(PROP_AUTO_T_OUT, PROP_TYPE_INT, minutes)
        self.coordinator.data.auto_t_out = minutes
        self.coordinator.async_set_updated_data(self.coordinator.data)
