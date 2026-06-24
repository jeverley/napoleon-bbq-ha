"""
Config flow handler package for napoleon_home.

This package implements the configuration and options flows for the integration.
The config flow handler class is re-exported here for the integration root's
config_flow.py to import (required by hassfest).

Package structure:
    config_flow.py: Main configuration flow (BLE discovery, user setup, reauth).
    options_flow.py: Options flow for post-setup settings (poll interval).
    schemas/: Voluptuous schemas for options forms.

For more information:
https://developers.home-assistant.io/docs/config_entries_config_flow_handler
"""

from __future__ import annotations

from .config_flow import NapoleonHomeConfigFlowHandler
from .options_flow import NapoleonHomeOptionsFlow
from .subentry_flow import NapoleonHomeGrillSubentryFlowHandler

__all__ = [
    "NapoleonHomeConfigFlowHandler",
    "NapoleonHomeGrillSubentryFlowHandler",
    "NapoleonHomeOptionsFlow",
]
