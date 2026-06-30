"""
Options flow schemas for napoleon_home.

Schemas for the options flow that allows users to modify integration settings
after initial configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from custom_components.napoleon_home.const import POLL_INTERVAL_S
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode

CONF_POLL_INTERVAL = "poll_interval"


def get_options_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """
    Get schema for the options flow.

    Args:
        defaults: Optional mapping of current option values used to pre-fill the form.

    Returns:
        Voluptuous schema for options configuration.

    """
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_POLL_INTERVAL,
                default=defaults.get(CONF_POLL_INTERVAL, POLL_INTERVAL_S),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=15,
                    max=300,
                    step=5,
                    unit_of_measurement="s",
                    mode=NumberSelectorMode.BOX,
                ),
            ),
        }
    )


__all__ = [
    "CONF_POLL_INTERVAL",
    "get_options_schema",
]
