"""Status binary sensor for napoleon_home."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.entity import NapoleonHomeEntity
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator

ENTITY_DESCRIPTIONS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class NapoleonHomeStatusBinarySensor(BinarySensorEntity, NapoleonHomeEntity):
    """Binary sensor indicating whether the grill is BLE-connected and authenticated."""

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialise the status sensor."""
        super().__init__(coordinator, entity_description)

    @property
    def available(self) -> bool:
        """Always expose status, even when the grill is disconnected."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the BLE session is connected and authenticated."""
        return self.coordinator.authenticated
