"""Target temperature number entities for napoleon_home."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import PROP_TGT_TEMPS, PROP_TYPE_DECIMAL
from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import UnitOfTemperature

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class NapoleonHomeTargetTempNumberEntityDescription(NumberEntityDescription):
    """Entity description for a Napoleon Home target temperature number.

    Attributes:
        probe: Probe number (1–4).

    """

    probe: int = 0


ENTITY_DESCRIPTIONS: tuple[NapoleonHomeTargetTempNumberEntityDescription, ...] = tuple(
    NapoleonHomeTargetTempNumberEntityDescription(
        key="grill_target" if probe == 4 else f"probe_{probe}_target",
        translation_key="grill_target" if probe == 4 else f"probe_{probe}_target",
        mode=NumberMode.BOX,
        native_step=1.0,
        probe=probe,
    )
    for probe in range(1, 5)
)


class NapoleonHomeTargetTempNumber(NumberEntity, NapoleonHomeEntity):
    """Number entity for setting a target temperature on a Napoleon Home probe.

    The native unit and min/max range adjust dynamically to match the grill's
    current temperature unit setting (TUNIT: 0 = Celsius, 1 = Fahrenheit).

    """

    entity_description: NapoleonHomeTargetTempNumberEntityDescription

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: NapoleonHomeTargetTempNumberEntityDescription,
    ) -> None:
        """Initialise the target temperature number."""
        super().__init__(coordinator, entity_description)

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the temperature unit matching the grill's current TUNIT setting."""
        return UnitOfTemperature.CELSIUS if self.coordinator.data.tunit == 0 else UnitOfTemperature.FAHRENHEIT

    @property
    def native_min_value(self) -> float:
        """Return the minimum settable temperature in the current unit."""
        return 40.0 if self.coordinator.data.tunit == 0 else 100.0

    @property
    def native_max_value(self) -> float:
        """Return the maximum settable temperature in the current unit."""
        return 380.0 if self.coordinator.data.tunit == 0 else 720.0

    @property
    def native_value(self) -> float | None:
        """Return the current target temperature, or None if not yet received."""
        return self.coordinator.data.target_temps.get(self.entity_description.probe)

    @property
    def available(self) -> bool:
        """Return availability for probe targets and grill target channels.

        Probe 1-3 targets are unavailable when physically unplugged.
        The grill target channel (probe slot 4 on this model) remains available
        whenever BLE is authenticated.

        """
        if self.entity_description.probe == 4:
            return self.coordinator.authenticated
        return self.coordinator.authenticated and self.coordinator.data.probe_connected(self.entity_description.probe)

    @property
    def icon(self) -> str:
        """Return icon for probe and grill target channels."""
        if self.entity_description.probe == 4:
            return "mdi:thermometer"
        return "mdi:thermometer-probe" if self.available else "mdi:thermometer-probe-off"

    async def async_set_native_value(self, value: float) -> None:
        """Set the target temperature for this probe on the grill."""
        prop_name = PROP_TGT_TEMPS[self.entity_description.probe - 1]
        await self.coordinator.async_set_property(prop_name, PROP_TYPE_DECIMAL, value)
