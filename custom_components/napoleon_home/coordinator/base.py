"""
Core BLE coordinator for napoleon_home.

This module manages the persistent Bluetooth LE connection to the Napoleon Prestige
grill. BLE connection lifecycle logic lives in ``listeners.py`` (mixed in via
``NapoleonHomeBLEMixin``). This module handles coordinator setup, data polling,
and clean shutdown.

For more information on coordinators:
https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.napoleon_home.config_flow_handler.schemas import CONF_POLL_INTERVAL
from custom_components.napoleon_home.const import CONF_DEVICES, CONF_LOCAL_KEY, DOMAIN, LOGGER, POLL_INTERVAL_S
from custom_components.napoleon_home.coordinator.listeners import NapoleonHomeBLEMixin
from custom_components.napoleon_home.data import NapoleonHomeGrillState
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from custom_components.napoleon_home.data import NapoleonHomeConfigEntry


class NapoleonHomeDataUpdateCoordinator(DataUpdateCoordinator[NapoleonHomeGrillState], NapoleonHomeBLEMixin):
    """
    BLE coordinator for the Napoleon Prestige grill.

    Inherits BLE connection lifecycle from ``NapoleonHomeBLEMixin`` (listeners.py)
    and HA coordinator machinery from ``DataUpdateCoordinator``.

    Responsibilities of this class:
        - Coordinator setup and initial state (``_async_setup``).
        - Periodic property polling when authenticated (``_async_update_data``).
        - Clean shutdown of BLE state and coordinator resources (``async_shutdown``).

    For more information on the BLE protocol:
    See _handover/CLAUDE.md — Protocol section.

    Attributes:
        config_entry: The hub config entry for this integration instance.

    """

    config_entry: NapoleonHomeConfigEntry

    def __init__(
        self,
        hass: Any,
        config_entry: NapoleonHomeConfigEntry,
        mac: str,
    ) -> None:
        """
        Initialise the coordinator.

        Args:
            hass: The Home Assistant instance.
            config_entry: The hub config entry (provides poll interval from options
                and the background task helper).
            mac: The BLE MAC address (``mac.lower()``) used as the key in
                ``entry.data[CONF_DEVICES]``.

        """
        self._poll_interval: int = config_entry.options.get(CONF_POLL_INTERVAL, POLL_INTERVAL_S)
        super().__init__(
            hass,
            LOGGER,
            name=f"{DOMAIN}_{mac}",
            update_interval=None,
        )
        self.config_entry = config_entry
        self._device_mac = mac
        device_data = config_entry.data[CONF_DEVICES][mac]
        self._init_ble(mac, device_data[CONF_LOCAL_KEY])

    @property
    def device_data(self) -> dict[str, Any]:
        """Return the device dict from entry.data for this coordinator's grill."""
        return self.config_entry.data[CONF_DEVICES][self._device_mac]

    @property
    def mac(self) -> str:
        """Return the BLE MAC address (lower-case) for this grill."""
        return self._device_mac

    async def _async_setup(self) -> None:
        """
        Set up the coordinator before the first data refresh.

        Initialises an empty grill state, then registers the BLE advertisement
        callback to connect when the grill powers on or is already advertising.

        This method is called automatically by Home Assistant during
        ``async_config_entry_first_refresh``.
        """
        self.data = NapoleonHomeGrillState()
        self._register_bt_callback()
        LOGGER.debug("Coordinator setup complete for Napoleon Home %s", self._mac)

    async def _async_update_data(self) -> NapoleonHomeGrillState:
        """
        Poll all Ayla properties via ``Gpr`` if the session is authenticated.

        When the grill is offline or authentication has not yet completed, the
        method returns the existing state without raising an error. Temperatures
        and state-change events are also propagated immediately via
        ``async_set_updated_data`` from the notification callback, so entities
        update as soon as the grill pushes a value rather than waiting for this
        cycle.

        Returns:
            The current ``NapoleonHomeGrillState`` snapshot.

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
