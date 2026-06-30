"""
API package for napoleon_home.

Architecture:
    Three-layer data flow: Entities → Coordinator → API Client.
    Only the coordinator should call the API client. Entities must never
    import or call the API client directly.

Exception hierarchy:
    NapoleonHomeApiClientError (base)
    ├── NapoleonHomeApiClientCommunicationError (network/timeout)
    └── NapoleonHomeApiClientAuthenticationError (401/403)

Coordinator exception mapping:
    ApiClientAuthenticationError → ConfigEntryAuthFailed (triggers reauth)
    ApiClientCommunicationError → UpdateFailed (auto-retry)
    ApiClientError             → UpdateFailed (auto-retry)
"""

from .client import (
    NapoleonHomeApiClient,
    NapoleonHomeApiClientAuthenticationError,
    NapoleonHomeApiClientCommunicationError,
    NapoleonHomeApiClientError,
)

__all__ = [
    "NapoleonHomeApiClient",
    "NapoleonHomeApiClientAuthenticationError",
    "NapoleonHomeApiClientCommunicationError",
    "NapoleonHomeApiClientError",
]
