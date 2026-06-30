"""
Entity package for napoleon_home.

Architecture:
    All platform entities inherit from ``(PlatformEntity, NapoleonHomeEntity)``.
    MRO order matters — the platform-specific class must come first, then the
    integration base class. Entities read data from ``coordinator.data`` and
    NEVER call the API client directly.

Unique IDs follow the pattern: ``{entry_id}_{description.key}``

See entity/base.py for the NapoleonHomeEntity base class.
"""

from __future__ import annotations

from .base import NapoleonHomeEntity

__all__ = ["NapoleonHomeEntity"]
