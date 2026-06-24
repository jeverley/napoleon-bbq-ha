"""
Core BLE coordinator for napoleon_bbq.

This module manages the persistent Bluetooth LE connection to the Napoleon Prestige
grill. BLE connection lifecycle logic lives in ``listeners.py`` (mixed in via
``NapoleonBBQBLEMixin``). This module handles coordinator setup, data polling,
and clean shutdown.

For more information on coordinators:
https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_bbq.config_flow_handler.schemas import CONF_POLL_INTERVAL
from custom_components.napoleon_bbq.const import CONF_LOCAL_KEY, CONF_MAC, DOMAIN, LOGGER, POLL_INTERVAL_S
from custom_components.napoleon_bbq.coordinator.listeners import NapoleonBBQBLEMixin
from custom_components.napoleon_bbq.data import NapoleonBBQGrillState
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from custom_components.napoleon_bbq.data import NapoleonBBQConfigEntry
    from homeassistant.config_entries import ConfigSubentry


class NapoleonBBQDataUpdateCoordinator(DataUpdateCoordinator[NapoleonBBQGrillState], NapoleonBBQBLEMixin):
    """
    BLE coordinator for the Napoleon Prestige grill.

    Inherits BLE connection lifecycle from ``NapoleonBBQBLEMixin`` (listeners.py)
    and HA coordinator machinery from ``DataUpdateCoordinator``.

    Responsibilities of this class:
        - Coordinator setup and initial state (``_async_setup``).
        - Periodic property polling when authenticated (``_async_update_data``).
        - Clean shutdown of BLE state and coordinator resources (``async_shutdown``).

    For more information on the BLE protocol:
    See _handover/CLAUDE.md — Protocol section.

    Attributes:
        config_entry: The hub config entry for this integration instance.
        subentry: The sub-entry containing this grill's MAC, DSN, and local key.

    """

    config_entry: NapoleonBBQConfigEntry

    def __init__(
        self,
        hass: Any,
        config_entry: NapoleonBBQConfigEntry,
        subentry: ConfigSubentry,
    ) -> None:
        """
        Initialise the coordinator.

        Args:
            hass: The Home Assistant instance.
            config_entry: The hub config entry (provides poll interval from options
                and the background task helper).
            subentry: The device sub-entry containing ``CONF_MAC`` and
                ``CONF_LOCAL_KEY`` in its data.

        """
        self._poll_interval: int = config_entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_S)
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{subentry.data[CONF_MAC]}",
            update_interval=None,
        )
        self.config_entry = config_entry
        self._subentry = subentry
        self._init_ble(subentry.data[CONF_MAC], subentry.data[CONF_LOCAL_KEY])

    @property
    def subentry(self) -> ConfigSubentry:
        """Return the device sub-entry associated with this coordinator."""
        return self._subentry

    async def _async_setup(self) -> None:
        """
        Set up the coordinator before the first data refresh.

        Initialises an empty grill state, then either connects immediately if the
        grill is already advertising or registers an advertisement callback to
        connect when the grill powers on.

        This method is called automatically by Home Assistant during
        ``async_config_entry_first_refresh``.
        """
        self.data = NapoleonBBQGrillState()
        device = async_ble_device_from_address(self.hass, self._mac, connectable=True)
        if device is not None:
            self.config_entry.async_create_background_task(
                self.hass,
                self._connect_and_run(device),
                f"napoleon_bbq_connect_{self._mac}",
            )
        else:
            self._register_bt_callback()
        LOGGER.debug("Coordinator setup complete for Napoleon BBQ %s", self._mac)

    async def _async_update_data(self) -> NapoleonBBQGrillState:
        """
        Poll all Ayla properties via ``Gpr`` if the session is authenticated.

        When the grill is offline or authentication has not yet completed, the
        method returns the existing state without raising an error. Temperatures
        and state-change events are also propagated immediately via
        ``async_set_updated_data`` from the notification callback, so entities
        update as soon as the grill pushes a value rather than waiting for this
        cycle.

        Returns:
            The current ``NapoleonBBQGrillState`` snapshot.

        Raises:
            UpdateFailed: If a BLE write error occurs during polling.

        """
        if not self.authenticated:
            return self.data
        try:
            await self._poll_properties()
        except Exception as exception:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from exception
        return self.data

    async def async_shutdown(self) -> None:
        """
        Shut down the coordinator cleanly.

        Tears down BLE state (cancels advertisement callback, disconnects client)
        then delegates to the DataUpdateCoordinator base class.
        """
        await self._shutdown_ble()
        await super().async_shutdown()
