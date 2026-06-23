"""Diagnostic sensors for napoleon_bbq."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator
    from custom_components.napoleon_bbq.data import NapoleonBBQGrillState
    from homeassistant.helpers.typing import StateType


@dataclass(frozen=True, kw_only=True)
class NapoleonBBQDiagnosticSensorEntityDescription(SensorEntityDescription):
    """
    Entity description for a Napoleon BBQ diagnostic sensor.

    Extends ``SensorEntityDescription`` with a ``value_fn`` callback so that
    one class can serve multiple sensors reading different fields from
    ``NapoleonBBQGrillState``.

    Attributes:
        value_fn: Callable that extracts the sensor value from the grill state.

    """

    value_fn: Callable[[NapoleonBBQGrillState], StateType] = lambda _: None


ENTITY_DESCRIPTIONS: tuple[NapoleonBBQDiagnosticSensorEntityDescription, ...] = (
    NapoleonBBQDiagnosticSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery_level,
    ),
    NapoleonBBQDiagnosticSensorEntityDescription(
        key="tank_weight",
        translation_key="tank_weight",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        icon="mdi:propane-tank",
        value_fn=lambda s: s.tank_weight,
    ),
    NapoleonBBQDiagnosticSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
        value_fn=lambda s: s.firmware_version,
    ),
)


class NapoleonBBQDiagnosticSensor(SensorEntity, NapoleonBBQEntity):
    """
    Diagnostic sensor for the Napoleon Prestige grill.

    Reads a single diagnostic value from ``NapoleonBBQGrillState`` via the
    ``value_fn`` callback in the entity description.

    """

    entity_description: NapoleonBBQDiagnosticSensorEntityDescription

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: NapoleonBBQDiagnosticSensorEntityDescription,
    ) -> None:
        """
        Initialise the diagnostic sensor.

        Args:
            coordinator: The BLE coordinator managing grill state.
            entity_description: The entity description with a ``value_fn`` callback.

        """
        super().__init__(coordinator, entity_description)

    @property
    def native_value(self) -> StateType:
        """Return the current sensor value via the description's value_fn callback."""
        return self.entity_description.value_fn(self.coordinator.data)
