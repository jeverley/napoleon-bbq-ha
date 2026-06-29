"""Probe temperature sensors for napoleon_home."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.const import UnitOfTemperature

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class NapoleonHomeProbeTempSensorEntityDescription(SensorEntityDescription):
    """
    Entity description for a Napoleon Home probe temperature sensor.

    Extends ``SensorEntityDescription`` with a ``probe`` field so that a single
    entity class can serve all four probe slots.

    Attributes:
        probe: Probe number (1–4).

    """

    probe: int = 0


ENTITY_DESCRIPTIONS: tuple[NapoleonHomeProbeTempSensorEntityDescription, ...] = tuple(
    NapoleonHomeProbeTempSensorEntityDescription(
        key="grill" if probe == 4 else f"probe_{probe}",
        translation_key="grill" if probe == 4 else f"probe_{probe}",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        probe=probe,
    )
    for probe in range(1, 5)
)


class NapoleonHomeProbeTempSensor(SensorEntity, NapoleonHomeEntity):
    """
    Temperature sensor for a single Napoleon Home probe.

    Reports the current probe temperature in the unit selected on the grill
    (Celsius or Fahrenheit per the ``TUNIT`` property). Returns ``None`` when
    the probe is not connected or has not yet been polled.

    """

    entity_description: NapoleonHomeProbeTempSensorEntityDescription

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: NapoleonHomeProbeTempSensorEntityDescription,
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
        """Return availability for probes and grill temperature channels.

        Probe 1-3 sensors are unavailable when physically unplugged.
        The grill temperature channel (probe slot 4 on this model) remains
        available whenever BLE is authenticated.

        """
        if self.entity_description.probe == 4:
            return self.coordinator.authenticated
        return self.coordinator.authenticated and self.coordinator.data.probe_connected(self.entity_description.probe)

    @property
    def icon(self) -> str:
        """Return icon for probe and grill temperature channels."""
        if self.entity_description.probe == 4:
            return "mdi:thermometer"
        return "mdi:thermometer-probe" if self.available else "mdi:thermometer-probe-off"
