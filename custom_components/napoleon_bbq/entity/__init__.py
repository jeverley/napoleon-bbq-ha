"""
Entity package for napoleon_bbq.

Architecture:
    All platform entities inherit from (PlatformEntity, NapoleonBBQEntity).
    MRO order matters — platform-specific class first, then the integration base.
    Entities read data from coordinator.data and NEVER call the API client directly.
    Unique IDs follow the pattern: {entry_id}_{description.key}

See entity/base.py for the NapoleonBBQEntity base class.
"""

from .base import NapoleonBBQEntity

__all__ = ["NapoleonBBQEntity"]
