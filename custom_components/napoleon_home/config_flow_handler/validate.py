"""Error types for napoleon_home BLE validation."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class NapoleonHomeNotProvisionedError(HomeAssistantError):
    """Raised when the grill is not provisioned via Napoleon app yet."""


class NapoleonHomeAlreadyBondedError(HomeAssistantError):
    """Raised when the grill rejects writes with ATT 0x05 (Insufficient Authentication).

    A provisioned grill disables new BLE bonding after it has been set up via the
    Napoleon app. The grill must be factory-reset to re-enable bonding, after which
    it must be provisioned again before the local key is available.
    """
