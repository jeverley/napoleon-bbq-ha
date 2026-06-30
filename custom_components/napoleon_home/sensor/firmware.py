"""Firmware version sensor for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

ENTITY_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:chip",
    ),
)


class NapoleonHomeFirmwareVersionSensor(SensorEntity, NapoleonHomeEntity):
    """Sensor reporting firmware version."""

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: SensorEntityDescription,
    ) -> None:
        """Initialise the firmware version sensor."""
        super().__init__(coordinator, entity_description)

    @property
    def native_value(self) -> str | None:
        """Return current firmware version."""
        return self.coordinator.data.firmware_version
