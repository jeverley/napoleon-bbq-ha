"""Probe temperature sensors for napoleon_bbq."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import UnitOfTemperature

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class NapoleonBBQProbeTempSensorEntityDescription(SensorEntityDescription):
    """
    Entity description for a Napoleon BBQ probe temperature sensor.

    Extends ``SensorEntityDescription`` with a ``probe`` field so that a single
    entity class can serve all four probe slots.

    Attributes:
        probe: Probe number (1–4).

    """

    probe: int = 0


ENTITY_DESCRIPTIONS: tuple[NapoleonBBQProbeTempSensorEntityDescription, ...] = tuple(
    NapoleonBBQProbeTempSensorEntityDescription(
        key=f"probe_{probe}_temp",
        translation_key=f"probe_{probe}_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        probe=probe,
    )
    for probe in range(1, 5)
)


class NapoleonBBQProbeTempSensor(SensorEntity, NapoleonBBQEntity):
    """
    Temperature sensor for a single Napoleon BBQ probe.

    Reports the current probe temperature in the unit selected on the grill
    (Celsius or Fahrenheit per the ``TUNIT`` property). Returns ``None`` when
    the probe is not connected or has not yet been polled.

    """

    entity_description: NapoleonBBQProbeTempSensorEntityDescription

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: NapoleonBBQProbeTempSensorEntityDescription,
    ) -> None:
        """
        Initialise the probe temperature sensor.

        Args:
            coordinator: The BLE coordinator managing grill state.
            entity_description: The entity description, including the probe number.

        """
        super().__init__(coordinator, entity_description)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the temperature unit matching the grill's current TUNIT setting."""
        return UnitOfTemperature.CELSIUS if self.coordinator.data.tunit == 0 else UnitOfTemperature.FAHRENHEIT

    @property
    def native_value(self) -> float | None:
        """Return the current probe temperature, or None if unavailable."""
        return self.coordinator.data.probe_temp(self.entity_description.probe)

    @property
    def available(self) -> bool:
        """Return True only when BLE is authenticated and the probe is physically connected."""
        return self.coordinator.authenticated and self.coordinator.data.probe_connected(self.entity_description.probe)
