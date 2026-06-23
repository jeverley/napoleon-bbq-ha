"""
Data update coordinator package for napoleon_bbq.

This package provides the BLE coordinator that manages the persistent connection
to the Napoleon Prestige grill and distributes state updates to all entities.

Package structure:
    base.py: Coordinator class (NapoleonBBQDataUpdateCoordinator) — setup, polling, shutdown.
    listeners.py: BLE connection lifecycle mixin (NapoleonBBQBLEMixin) — advertisement,
        connect, authenticate, notification routing, GATT write helpers.

For more information on coordinators:
https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
"""

from __future__ import annotations

from .base import NapoleonBBQDataUpdateCoordinator

__all__ = ["NapoleonBBQDataUpdateCoordinator"]
