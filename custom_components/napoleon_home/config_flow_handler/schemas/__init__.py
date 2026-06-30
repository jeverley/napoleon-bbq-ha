"""
Data schemas for config flow forms in napoleon_home.

This package contains voluptuous schemas used in the options flow.

Package structure:
    options.py: Options flow schema (poll interval).
"""

from __future__ import annotations

from custom_components.napoleon_home.config_flow_handler.schemas.options import CONF_POLL_INTERVAL, get_options_schema

__all__ = [
    "CONF_POLL_INTERVAL",
    "get_options_schema",
]
