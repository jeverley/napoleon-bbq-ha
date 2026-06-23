"""Connectivity binary sensor for napoleon_bbq."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_bbq.entity import NapoleonBBQEntity
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.coordinator import NapoleonBBQDataUpdateCoordinator

ENTITY_DESCRIPTIONS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class NapoleonBBQConnectedBinarySensor(BinarySensorEntity, NapoleonBBQEntity):
    """Binary sensor indicating whether the grill is BLE-connected and authenticated."""

    def __init__(
        self,
        coordinator: NapoleonBBQDataUpdateCoordinator,
        entity_description: BinarySensorEntityDescription,
    ) -> None:
        """Initialise the connectivity sensor."""
        super().__init__(coordinator, entity_description)

    @property
    def is_on(self) -> bool:
        """Return True when the BLE session is connected and authenticated."""
        return self.coordinator.authenticated
