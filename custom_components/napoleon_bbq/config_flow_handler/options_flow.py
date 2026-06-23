"""
Options flow for napoleon_bbq.

This module implements the options flow that allows users to modify integration
settings after initial configuration.

Currently configurable options:
    poll_interval: How often (in seconds) the coordinator polls all grill
        properties via ``Gpr`` when the grill has active WiFi/MQTT. Only
        temperature values need polling; state changes arrive via unsolicited
        ``Odp`` pushes regardless of this setting. Default: 30 s.

For more information:
https://developers.home-assistant.io/docs/config_entries_options_flow_handler
"""

from __future__ import annotations

from typing import Any

from custom_components.napoleon_bbq.config_flow_handler.schemas import get_options_schema
from homeassistant import config_entries


class NapoleonBBQOptionsFlow(config_entries.OptionsFlow):
    """
    Handle the options flow for napoleon_bbq.

    Provides a single form for all configurable integration settings. Changes
    take effect immediately via entry reload (handled automatically by HA when
    the entry uses the ``OptionsFlowWithReload`` mixin — registered as a reload
    listener in ``async_setup_entry``).

    For more information:
    https://developers.home-assistant.io/docs/config_entries_options_flow_handler

    """

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> config_entries.ConfigFlowResult:
        """
        Manage the options for the integration.

        Pre-fills the form with current option values and saves on submission.

        Args:
            user_input: The submitted option values, or None to show the form.

        Returns:
            A form result for initial display, or an options entry result on save.

        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=get_options_schema(self.config_entry.options),
        )


__all__ = ["NapoleonBBQOptionsFlow"]
