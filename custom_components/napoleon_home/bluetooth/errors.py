"""BLE session errors for napoleon_home."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class NapoleonHomeNotProvisionedError(HomeAssistantError):
    """Raised when the grill has not been provisioned via the Napoleon app (s:6)."""


class NapoleonHomeAlreadyBondedError(HomeAssistantError):
    """Raised when the grill refuses writes with ATT 0x05 — bonded to another device."""
