"""
Base entity class for napoleon_home.

This module provides the base entity class that all integration entities inherit from.
It handles common functionality such as coordinator integration, device info, unique ID
generation, and entity naming conventions.

All platform entities must inherit using the pattern:
    ``class MyEntity(PlatformEntity, NapoleonHomeEntity)``

MRO order matters — the platform-specific class must come first.

For more information on entities:
https://developers.home-assistant.io/docs/core/entity
https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.napoleon_home.const import ATTRIBUTION
from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator
from custom_components.napoleon_home.entity_utils.device_info import build_device_info
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity import EntityDescription


class NapoleonHomeEntity(CoordinatorEntity[NapoleonHomeDataUpdateCoordinator]):
    """
    Base entity class for napoleon_home.

    All entities in this integration inherit from this class, which provides:
    - Automatic coordinator updates via ``CoordinatorEntity``.
    - Device info registered against the grill's MAC address.
    - Unique ID generation from ``{mac_lowercase}_{description.key}``.
    - Attribution and HA entity naming via ``_attr_has_entity_name = True``.

    Platform entities must set their own ``native_value``, ``is_on``, or other
    platform-required properties. They must not call the API client directly.

    For more information:
    https://developers.home-assistant.io/docs/core/entity

    """

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NapoleonHomeDataUpdateCoordinator,
        entity_description: EntityDescription,
    ) -> None:
        """
        Initialise the base entity.

        Args:
            coordinator: The BLE coordinator managing state for this config entry.
            entity_description: The entity description defining static entity metadata
                (key, name, device class, unit of measurement, etc.).

        """
        super().__init__(coordinator)
        self.entity_description = entity_description
        self._attr_unique_id = f"{coordinator.mac}_{entity_description.key}"
        self._attr_device_info = build_device_info(coordinator)

    @property
    def available(self) -> bool:
        """Return True when the grill BLE session is authenticated."""
        return self.coordinator.authenticated
