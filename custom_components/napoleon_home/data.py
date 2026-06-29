"""
Custom types and data models for napoleon_home.

This module defines:
- NapoleonHomeGrillState: live device state updated by the coordinator from BLE pushes/polls
- NapoleonHomeCoordinators: type alias for the runtime_data dict keyed by sub-entry ID
- NapoleonHomeConfigEntry: type alias for type-safe access to the config entry

Access pattern: entry.runtime_data[subentry_id]
Coordinator data: coordinator.data (a NapoleonHomeGrillState instance)

For more information:
https://developers.home-assistant.io/docs/config_entries_index
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from custom_components.napoleon_home.const import (
    PROBE_DISCONNECTED,
    PROP_AUTO_T_OUT,
    PROP_BATTERY_LOW_ALERT,
    PROP_BRT_LVL,
    PROP_BSMODE,
    PROP_BT_LVL,
    PROP_CNTRY,
    PROP_EMTY_TNK_W,
    PROP_F_TNKWT,
    PROP_GS_TNK_NAME,
    PROP_GS_UNT,
    PROP_LCD_OFF,
    PROP_PRB_STAT,
    PROP_PRB_TEMPS,
    PROP_REGN,
    PROP_TGT_TEMPS,
    PROP_TNK_WT,
    PROP_TUNIT,
    PROP_VERSION,
)

if TYPE_CHECKING:
    from custom_components.napoleon_home.coordinator import NapoleonHomeDataUpdateCoordinator
    from homeassistant.config_entries import ConfigEntry

type NapoleonHomeCoordinators = dict[str, "NapoleonHomeDataUpdateCoordinator"]
type NapoleonHomeConfigEntry = ConfigEntry[NapoleonHomeCoordinators]


@dataclass
class NapoleonHomeGrillState:
    """Snapshot of all polled grill properties.

    Updated by the coordinator from incoming Ayla BLE protocol messages:
    - Odp (unsolicited push): state changes the grill sends proactively.
    - gpr (response to Gpr poll): current value for a specific property.

    Temperature values are in the unit indicated by tunit (0=°C, 1=°F).

    Attributes:
        tunit: Temperature unit — 0 = Celsius, 1 = Fahrenheit.
        bsmode: Battery/screen saver mode enabled state.
        lcd_off: Knob backlights off state — True = off.
        brt_lvl: Display brightness level (1=low, 3=mid, 5=high). None if not yet polled.
        auto_t_out: Auto shutoff timeout in hours (1–24). None if not yet polled.
        gs_unt: Gas unit — 0 = kg, 1 = lbs.
        probe_temps: Current probe temperatures keyed by probe number (1–4). None = not yet received.
        probe_stat: Probe connected state bitmask (bit 0 = probe 1, bit 3 = probe 4).
        target_temps: Target temperatures keyed by probe number (1–4). None = not yet received.
        battery_level: Battery level percentage (BT_LVL 0-5 × 20). None if not yet polled.
        battery_low: True if the battery low alert is active.
        tank_weight: Current gas tank weight in gs_unt units. None if not configured or not yet polled.
        empty_tank_weight: Empty tank calibration weight in gs_unt units. None if not yet polled.
        full_tank_weight: Full tank calibration weight in gs_unt units. None if not yet polled.
        region: Grill region code. None if not yet polled.
        country: Grill country code. None if not yet polled.
        gas_tank_name: Configured gas tank name. None if not yet polled.
        firmware_version: Grill firmware version string. None if not yet polled.

    """

    # Settings
    tunit: int = 0
    bsmode: bool = False
    lcd_off: bool = False
    brt_lvl: int | None = None
    auto_t_out: int | None = None
    gs_unt: int = 0

    # Probe temperatures (°C or °F per tunit; None = not yet received)
    probe_temps: dict[int, float | None] = field(default_factory=lambda: {1: None, 2: None, 3: None, 4: None})

    # Probe connected state bitmask (bit 0 = probe 1, …, bit 3 = probe 4)
    probe_stat: int = 0

    # Target temperatures per probe (None = not yet received)
    target_temps: dict[int, float | None] = field(default_factory=lambda: {1: None, 2: None, 3: None, 4: None})

    # System
    battery_level: int | None = None
    battery_low: bool = False
    tank_weight: float | None = None
    empty_tank_weight: float | None = None
    full_tank_weight: float | None = None
    region: str | None = None
    country: str | None = None
    gas_tank_name: str | None = None
    firmware_version: str | None = None

    def probe_connected(self, probe: int) -> bool:
        """Return True if the given probe (1-indexed) is connected.

        Args:
            probe: Probe number (1–4).

        Returns:
            True if the corresponding bit in probe_stat is set.

        """
        return bool(self.probe_stat & (1 << (probe - 1)))

    def probe_temp(self, probe: int) -> float | None:
        """Return the current temperature for a probe, or None if unavailable.

        Returns None when the probe is not connected (per probe_stat), the value
        has not yet been received from the grill, or the value equals the
        disconnected sentinel (4095).

        Args:
            probe: Probe number (1–4).

        Returns:
            The temperature in the unit indicated by tunit, or None.

        """
        if not self.probe_connected(probe):
            return None
        val = self.probe_temps.get(probe)
        if val is None or val >= PROBE_DISCONNECTED:
            return None
        return val

    def update_from_property(self, name: str, value: Any) -> None:
        """Apply a single Ayla property value received from the grill.

        Called by the coordinator for each incoming gpr response or Odp push.

        Args:
            name: The Ayla property name (e.g. "TUNIT", "PRB_TMP_ONE").
            value: The raw property value from the protocol message.

        """
        if name == PROP_TUNIT:
            self.tunit = int(value)
        elif name == PROP_BSMODE:
            self.bsmode = bool(value)
        elif name == PROP_LCD_OFF:
            self.lcd_off = bool(value)
        elif name == PROP_BRT_LVL:
            self.brt_lvl = int(value)
        elif name == PROP_AUTO_T_OUT:
            self.auto_t_out = int(value)
        elif name == PROP_GS_UNT:
            self.gs_unt = int(value)
        elif name == PROP_REGN:
            self.region = str(value) if value != "" else None
        elif name == PROP_CNTRY:
            self.country = str(value) if value != "" else None
        elif name == PROP_GS_TNK_NAME:
            self.gas_tank_name = str(value) if value != "" else None
        elif name == PROP_PRB_STAT:
            self.probe_stat = int(value)
        elif name == PROP_BT_LVL:
            self.battery_level = int(value) * 20  # 0-5 bar scale → 0-100%
        elif name == PROP_BATTERY_LOW_ALERT:
            self.battery_low = bool(value)
        elif name == PROP_TNK_WT:
            # -14400 is the sentinel value indicating the gas tank has not been configured.
            self.tank_weight = float(value) if value != -14400 else None
        elif name == PROP_EMTY_TNK_W:
            self.empty_tank_weight = float(value) if value != "" else None
        elif name == PROP_F_TNKWT:
            self.full_tank_weight = float(value) if value != "" else None
        elif name == PROP_VERSION:
            self.firmware_version = str(value)
        elif name in PROP_PRB_TEMPS:
            probe = PROP_PRB_TEMPS.index(name) + 1
            self.probe_temps[probe] = float(value) if value != "" else None
        elif name in PROP_TGT_TEMPS:
            probe = PROP_TGT_TEMPS.index(name) + 1
            self.target_temps[probe] = float(value) if value != "" else None
