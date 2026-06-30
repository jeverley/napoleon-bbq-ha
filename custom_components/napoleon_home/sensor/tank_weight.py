"""Tank weight sensor for napoleon_home."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfMass

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator
    from custom_components.napoleon_home.data import NapoleonHomeGrillState
    from homeassistant.helpers.typing import StateType

ENTITY_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="tank_weight",
        translation_key="tank_weight",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:propane-tank",
    ),
)


@dataclass(frozen=True, kw_only=True)
class NapoleonHomeTankDebugSensorEntityDescription(SensorEntityDescription):
    """Entity description for debug tank metadata sensors."""

    value_fn: Callable[[NapoleonHomeGrillState], StateType] = lambda _: None


DEBUG_ENTITY_DESCRIPTIONS: tuple[NapoleonHomeTankDebugSensorEntityDescription, ...] = (
    NapoleonHomeTankDebugSensorEntityDescription(
        key="gas_tank_name",
        translation_key="gas_tank_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:propane-tank",
        value_fn=lambda s: s.gas_tank_name,
    ),
    NapoleonHomeTankDebugSensorEntityDescription(
        key="region",
        translation_key="region",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:earth",
        value_fn=lambda s: s.region,
    ),
    NapoleonHomeTankDebugSensorEntityDescription(
        key="country",
        translation_key="country",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:flag",
        value_fn=lambda s: s.country,
    ),
)


class NapoleonHomeTankWeightSensor(SensorEntity, NapoleonHomeEntity):
    """Sensor reporting current tank weight."""

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialise the tank weight sensor."""
        super().__init__(coordinator, entity_description)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return tank weight unit based on grill setting."""
        return UnitOfMass.POUNDS if self.coordinator.data.gs_unt == 1 else UnitOfMass.KILOGRAMS

    @property
    def native_value(self) -> float | None:
        """Return current tank weight."""
        return self.coordinator.data.tank_weight


class NapoleonHomeTankDebugSensor(SensorEntity, NapoleonHomeEntity):
    """Debug sensor for tank metadata fields."""

    entity_description: NapoleonHomeTankDebugSensorEntityDescription

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: NapoleonHomeTankDebugSensorEntityDescription,
    ) -> None:
        """Initialise the debug tank metadata sensor."""
        super().__init__(coordinator, entity_description)

    @property
    def native_value(self) -> StateType:
        """Return current debug metadata value."""
        return self.entity_description.value_fn(self.coordinator.data)
