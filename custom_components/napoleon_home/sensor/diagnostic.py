"""Diagnostic sensors for napoleon_home."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfMass

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator
    from custom_components.napoleon_home.data import NapoleonHomeGrillState
    from homeassistant.helpers.typing import StateType


@dataclass(frozen=True, kw_only=True)
class NapoleonHomeDiagnosticSensorEntityDescription(SensorEntityDescription):
    """
    Entity description for a Napoleon Home diagnostic sensor.

    Extends ``SensorEntityDescription`` with a ``value_fn`` callback so that
    one class can serve multiple sensors reading different fields from
    ``NapoleonHomeGrillState``.

    Attributes:
        value_fn: Callable that extracts the sensor value from the grill state.

    """

    value_fn: Callable[[NapoleonHomeGrillState], StateType] = lambda _: None


ENTITY_DESCRIPTIONS: tuple[NapoleonHomeDiagnosticSensorEntityDescription, ...] = (
    NapoleonHomeDiagnosticSensorEntityDescription(
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.battery_level,
    ),
    NapoleonHomeDiagnosticSensorEntityDescription(
        key="tank_weight",
        translation_key="tank_weight",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        icon="mdi:propane-tank",
        value_fn=lambda s: s.tank_weight,
    ),
    NapoleonHomeDiagnosticSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
        value_fn=lambda s: s.firmware_version,
    ),
)


class NapoleonHomeDiagnosticSensor(SensorEntity, NapoleonHomeEntity):
    """
    Diagnostic sensor for the Napoleon Prestige grill.

    Reads a single diagnostic value from ``NapoleonHomeGrillState`` via the
    ``value_fn`` callback in the entity description.

    """

    entity_description: NapoleonHomeDiagnosticSensorEntityDescription

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: NapoleonHomeDiagnosticSensorEntityDescription,
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
