"""Tank calibration number entities for napoleon_home."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PROP_EMTY_TNK_W, PROP_F_TNKWT, PROP_TYPE_INT
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfMass

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class NapoleonHomeTankCalibrationNumberEntityDescription(NumberEntityDescription):
    """Entity description for tank calibration numbers."""

    property_name: str


ENTITY_DESCRIPTIONS: tuple[NapoleonHomeTankCalibrationNumberEntityDescription, ...] = (
    NapoleonHomeTankCalibrationNumberEntityDescription(
        key="empty_tank_weight",
        translation_key="empty_tank_weight",
        icon="mdi:propane-tank-outline",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=200,
        native_step=1,
        property_name=PROP_EMTY_TNK_W,
    ),
    NapoleonHomeTankCalibrationNumberEntityDescription(
        key="full_tank_weight",
        translation_key="full_tank_weight",
        icon="mdi:propane-tank",
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=200,
        native_step=1,
        property_name=PROP_F_TNKWT,
    ),
)


class NapoleonHomeTankCalibrationNumber(NumberEntity, NapoleonHomeEntity):
    """Number entities for empty/full tank calibration values."""

    entity_description: NapoleonHomeTankCalibrationNumberEntityDescription

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: NapoleonHomeTankCalibrationNumberEntityDescription,
    ) -> None:
        """Initialise the tank calibration number."""
        super().__init__(coordinator, entity_description)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return mass unit following the grill tank unit setting."""
        return UnitOfMass.POUNDS if self.coordinator.data.gs_unt == 1 else UnitOfMass.KILOGRAMS

    @property
    def native_value(self) -> float | None:
        """Return current calibration value."""
        if self.entity_description.property_name == PROP_EMTY_TNK_W:
            return self.coordinator.data.empty_tank_weight
        return self.coordinator.data.full_tank_weight

    async def async_set_native_value(self, value: float) -> None:
        """Set calibration value on the grill."""
        int_value = int(value)
        await self.coordinator.async_set_property(self.entity_description.property_name, PROP_TYPE_INT, int_value)
        if self.entity_description.property_name == PROP_EMTY_TNK_W:
            self.coordinator.data.empty_tank_weight = float(int_value)
        else:
            self.coordinator.data.full_tank_weight = float(int_value)
        self.coordinator.async_set_updated_data(self.coordinator.data)
