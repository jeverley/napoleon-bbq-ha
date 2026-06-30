"""
Ayla cloud API client for napoleon_home.

This module provides the HTTP client used during config flow setup to authenticate
with the Ayla IoT cloud and fetch the per-device BLE local key required for the
Ayla Local Control v2 handshake.

After initial setup the local key, key ID, and Ayla tokens are stored in the
config entry. Tokens are refreshed on-demand (only when a cloud call is actually
needed). In normal steady-state operation there are zero Ayla API calls.

For more information on the Ayla cloud API:
See _handover/CLAUDE.md — Cloud API section.

For more information on creating API clients:
https://developers.home-assistant.io/docs/api_lib_index
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import socket
import time
from typing import Any

import aiohttp

from custom_components.napoleon_home.const import LOGGER, _AylaRegion


class NapoleonHomeApiClientError(Exception):
    """Base exception to indicate a general API error."""


class NapoleonHomeApiClientCommunicationError(
    NapoleonHomeApiClientError,
):
    """Exception to indicate a communication error with the Ayla cloud."""


class NapoleonHomeApiClientAuthenticationError(
    NapoleonHomeApiClientError,
):
    """Exception to indicate an authentication error with the Ayla cloud."""


def _verify_response_or_raise(response: aiohttp.ClientResponse) -> None:
    """
    Verify that the Ayla cloud response is valid.

    Raises appropriate exceptions for authentication and HTTP errors.

    Args:
        response: The aiohttp ClientResponse to verify.

    Raises:
        NapoleonHomeApiClientAuthenticationError: For 401/403 responses.
        aiohttp.ClientResponseError: For other HTTP error responses.

    """
    if response.status in (401, 403):
        msg = "Invalid credentials"
        raise NapoleonHomeApiClientAuthenticationError(
            msg,
        )
    response.raise_for_status()


class NapoleonHomeApiClient:
    """
    Ayla cloud HTTP client for the napoleon_home integration.

    Used at config flow time to authenticate the user, discover Napoleon Prestige
    grills, and fetch per-device BLE local keys. The keys, key IDs, and Ayla
    tokens are persisted in the config entry. Tokens are refreshed on-demand
    only when an actual cloud call is required.

    Sign-in flow:
    1. POST to the Ayla user API with Napoleon app credentials and the user's
       email and password to obtain ``access_token``, ``refresh_token``, and
       ``expires_in``.
    2. GET ``/apiv1/devices.json`` to discover grills.
    3. GET ``/apiv1/devices/{dsn}/connection_config.json`` to obtain
       ``local_key`` and ``local_key_id`` per grill.

    For more information on the Ayla cloud API:
    See _handover/CLAUDE.md — Cloud API section.

    Attributes:
        _region: The Ayla region configuration (endpoints and app credentials).
        _session: The shared aiohttp ClientSession from Home Assistant.

    """

    def __init__(
        self,
        region: _AylaRegion,
        session: aiohttp.ClientSession,
    ) -> None:
        """
        Initialise the Ayla cloud API client for a specific region.

        Args:
            region: The Ayla region configuration (_AylaRegion named tuple)
                containing API hostnames, app credentials, and OEM model filter.
            session: The aiohttp ClientSession to use for requests (provided
                by Home Assistant via async_get_clientsession).

        """
        self._region = region
        self._session = session

    async def async_get_local_key(
        self,
        username: str,
        password: str,
        dsn: str | None = None,
    ) -> tuple[str, str, int, str, str, float]:
        """
        Sign in and return the DSN, local key, key ID, and fresh tokens.

        If a DSN is provided the local key is fetched for that specific device.
        Otherwise, the user's device list is queried and the first Napoleon
        Prestige grill matching the region's OEM model is used.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.
            dsn: Optional device serial number. Auto-discovered when not provided.

        Returns:
            ``(dsn, local_key, local_key_id, access_token, refresh_token, token_expiry)``

        Raises:
            NapoleonHomeApiClientAuthenticationError: If sign-in fails.
            NapoleonHomeApiClientCommunicationError: On network errors.
            NapoleonHomeApiClientError: If no Napoleon Prestige grill is found.

        """
        access_token, refresh_token, expiry = await self._async_sign_in(username, password)
        if dsn is None:
            devices = await self._async_list_devices(access_token)
            if not devices:
                msg = f"No Napoleon Prestige grill found in Ayla account (expected OEM model '{self._region.prestige_oem_model}')"
                raise NapoleonHomeApiClientError(msg)
            dsn = devices[0][0]
        local_key, local_key_id = await self._async_fetch_local_key(access_token, dsn)
        return dsn, local_key, local_key_id, access_token, refresh_token, expiry

    async def async_list_devices(
        self,
        username: str,
        password: str,
    ) -> tuple[list[tuple[str, str, str]], str, str, float]:
        """
        Sign in and return all Napoleon grills plus fresh tokens.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.

        Returns:
            ``(devices, access_token, refresh_token, token_expiry)`` where
            ``devices`` is a list of ``(dsn, display_name, mac)`` tuples.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If sign-in fails.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        access_token, refresh_token, expiry = await self._async_sign_in(username, password)
        devices = await self._async_list_devices(access_token)
        return devices, access_token, refresh_token, expiry

    async def async_refresh_local_keys(
        self,
        username: str,
        password: str,
        dsns: list[str],
    ) -> tuple[list[tuple[str, int]], str, str, float]:
        """
        Sign in once and fetch fresh local keys for the given list of DSNs.

        Used during reauthentication to refresh all sub-entries in a single
        sign-in round-trip.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.
            dsns: List of Ayla device serial numbers to refresh.

        Returns:
            ``(keys, access_token, refresh_token, token_expiry)`` where ``keys``
            is a list of ``(local_key, local_key_id)`` tuples in the same
            order as ``dsns``.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If sign-in fails.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        access_token, refresh_token, expiry = await self._async_sign_in(username, password)
        keys = list(await asyncio.gather(*[self._async_fetch_local_key(access_token, dsn) for dsn in dsns]))
        return keys, access_token, refresh_token, expiry

    async def async_refresh_token(
        self,
        refresh_token: str,
    ) -> tuple[str, str, float]:
        """
        Exchange a refresh token for a new access token without user credentials.

        Uses the same sign-in endpoint with a ``refresh_token`` field instead of
        email and password. This is used for on-demand silent token refresh when
        a stored access token has expired.

        Args:
            refresh_token: The previously stored Ayla refresh token.

        Returns:
            ``(access_token, refresh_token, token_expiry)`` with fresh values.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If the refresh token is
                revoked or invalid (401/403).
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        url = f"https://{self._region.user_host}/users/sign_in.json"
        body: dict[str, Any] = {
            "user": {
                "refresh_token": refresh_token,
                "application": {
                    "app_id": self._region.app_id,
                    "app_secret": self._region.app_secret,
                },
            }
        }
        data = await self._api_wrapper(method="post", url=url, json=body)
        new_access: str = data["access_token"]
        new_refresh: str = data.get("refresh_token", refresh_token)
        expires_in = int(data.get("expires_in", 86400))
        expiry = time.time() + expires_in
        return new_access, new_refresh, expiry

    async def async_fetch_key(
        self,
        access_token: str,
        dsn: str,
    ) -> tuple[str, int]:
        """
        Fetch the local key and key ID for a DSN using an existing access token.

        Avoids re-signing in when a valid token is already available.

        Args:
            access_token: A valid Ayla access token.
            dsn: The Ayla device serial number.

        Returns:
            ``(local_key, local_key_id)``

        Raises:
            NapoleonHomeApiClientAuthenticationError: If the token is invalid.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        return await self._async_fetch_local_key(access_token, dsn)

    async def async_fetch_device_by_mac(
        self,
        access_token: str,
        mac: str,
    ) -> tuple[str, str, str, int] | None:
        """
        Find a device by its BLE MAC address and fetch its local key.

        Calls ``devices.json`` to find the matching DSN, then fetches
        ``connection_config.json`` for that DSN.

        Args:
            access_token: A valid Ayla access token.
            mac: BLE MAC address to search for, formatted as ``"AA:BB:CC:DD:EE:FF"``.

        Returns:
            ``(dsn, name, local_key, local_key_id)`` or ``None`` if no device
            with that MAC exists in the account.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If the token is invalid.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        devices = await self._async_list_devices(access_token)
        match = next((d for d in devices if d[2].lower() == mac.lower()), None)
        if match is None:
            return None
        dsn, name, _ = match
        local_key, local_key_id = await self._async_fetch_local_key(access_token, dsn)
        return dsn, name, local_key, local_key_id

    async def async_fetch_device_by_possible_macs(
        self,
        access_token: str,
        mac_candidates: Iterable[str],
    ) -> tuple[str, str, str, int] | None:
        """
        Find a device by trying multiple possible MAC addresses.

        This helps when Ayla returns a sibling interface MAC (for example Wi-Fi)
        instead of the BLE advertising MAC. Candidate order is preserved so callers
        can prioritise exact and then fuzzy/offset variants.

        Args:
            access_token: A valid Ayla access token.
            mac_candidates: Ordered candidate MAC addresses to try.

        Returns:
            ``(dsn, name, local_key, local_key_id)`` or ``None`` if no candidate
            matches an Ayla device record.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If the token is invalid.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        candidates = [candidate.strip().lower() for candidate in mac_candidates if candidate.strip()]
        if not candidates:
            return None

        devices = await self._async_list_devices(access_token)
        devices_by_mac = {device_mac.lower(): (dsn, name) for dsn, name, device_mac in devices if device_mac}

        for candidate in candidates:
            match = devices_by_mac.get(candidate)
            if match is None:
                continue
            dsn, name = match
            local_key, local_key_id = await self._async_fetch_local_key(access_token, dsn)
            return dsn, name, local_key, local_key_id

        return None

    async def async_check_key(
        self,
        access_token: str,
        dsn: str,
        current_key_id: int,
    ) -> tuple[str, int] | None:
        """
        Check whether the local key has rotated using a stored Ayla access token.

        Fetches the current connection config without re-signing in. Returns the
        new key only if ``local_key_id`` differs from ``current_key_id``.

        Args:
            access_token: A previously stored Ayla access token.
            dsn: Ayla device serial number.
            current_key_id: The ``local_key_id`` stored in the sub-entry.

        Returns:
            ``(local_key, local_key_id)`` if the key has rotated, else ``None``.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If the token has expired.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        local_key, local_key_id = await self._async_fetch_local_key(access_token, dsn)
        if local_key_id == current_key_id:
            return None
        return local_key, local_key_id

    async def _async_sign_in(self, username: str, password: str) -> tuple[str, str, float]:
        """
        Authenticate with the Ayla user API and return tokens and expiry.

        Posts to ``/users/sign_in.json`` with the Napoleon application credentials
        and the user's account email and password.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.

        Returns:
            ``(access_token, refresh_token, expiry)`` where ``expiry`` is a Unix
            timestamp. ``expires_in`` from the response (seconds) is added to
            ``time.time()``; falls back to 86400 s if absent.

        Raises:
            NapoleonHomeApiClientAuthenticationError: On 401/403 responses.
            NapoleonHomeApiClientCommunicationError: On network errors or timeouts.

        """
        url = f"https://{self._region.user_host}/users/sign_in.json"
        body: dict[str, Any] = {
            "user": {
                "email": username,
                "password": password,
                "application": {
                    "app_id": self._region.app_id,
                    "app_secret": self._region.app_secret,
                },
            }
        }
        data = await self._api_wrapper(method="post", url=url, json=body)
        access_token: str = data["access_token"]
        refresh_token: str = data.get("refresh_token", "")
        expires_in: int = int(data.get("expires_in", 86400))
        expiry: float = time.time() + expires_in
        return access_token, refresh_token, expiry

    async def _async_list_devices(self, access_token: str) -> list[tuple[str, str, str]]:
        """
        List all Napoleon Prestige grills and return their DSN, name, and MAC.

        Queries ``/apiv1/devices.json`` and filters by the OEM model string defined
        in the region configuration.

        Args:
            access_token: A valid Ayla access token from ``_async_sign_in``.

        Returns:
            A list of ``(dsn, display_name, mac)`` tuples. ``mac`` is formatted
            as ``"AA:BB:CC:DD:EE:FF"`` or an empty string if not present.

        Raises:
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        url = f"https://{self._region.device_host}/apiv1/devices.json"
        headers = {"Authorization": f"auth_token {access_token}"}
        data = await self._api_wrapper(method="get", url=url, headers=headers)

        prestige_model = self._region.prestige_oem_model
        devices: list[tuple[str, str, str]] = []
        for entry in data:
            device = entry.get("device", {})
            if device.get("oem_model") == prestige_model:
                dsn: str = device["dsn"]
                name: str = device.get("friendly_name") or device.get("product_name") or dsn
                raw_mac: str = device.get("mac", "")
                mac = ":".join(raw_mac[i : i + 2].upper() for i in range(0, 12, 2)) if len(raw_mac) == 12 else ""
                LOGGER.debug("Found Napoleon Prestige grill: DSN=%s name=%r mac=%s", dsn, name, mac)
                devices.append((dsn, name, mac))
        return devices

    async def _async_fetch_local_key(self, access_token: str, dsn: str) -> tuple[str, int]:
        """
        Fetch the BLE local key and key ID for a specific Ayla device DSN.

        Queries ``/apiv1/devices/{dsn}/connection_config.json`` and returns the
        ``local_key`` and ``local_key_id`` fields.

        Args:
            access_token: A valid Ayla access token from ``_async_sign_in``.
            dsn: The Ayla device serial number.

        Returns:
            ``(local_key, local_key_id)`` where ``local_key`` is the
            base64-encoded BLE authentication key and ``local_key_id`` is an
            integer that increments on each key rotation.

        Raises:
            NapoleonHomeApiClientAuthenticationError: On 401/403 responses.
            NapoleonHomeApiClientCommunicationError: On network errors or timeouts.

        """
        url = f"https://{self._region.device_host}/apiv1/devices/{dsn}/connection_config.json"
        headers = {"Authorization": f"auth_token {access_token}"}
        data = await self._api_wrapper(method="get", url=url, headers=headers)
        local_key: str = data["local_key"]
        local_key_id: int = int(data["local_key_id"])
        return local_key, local_key_id

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """
        Wrapper for Ayla cloud HTTP requests with standardised error handling.

        All HTTP communication passes through this method, which maps network
        and HTTP errors to the integration's exception hierarchy.

        Args:
            method: The HTTP method string (``"get"``, ``"post"``, etc.).
            url: The full request URL.
            headers: Optional additional request headers.
            json: Optional JSON-serialisable body dict (sent as ``application/json``).

        Returns:
            The parsed JSON response body as a dict or list.

        Raises:
            NapoleonHomeApiClientAuthenticationError: For HTTP 401/403 responses.
            NapoleonHomeApiClientCommunicationError: For network errors, DNS failures,
                or request timeouts.
            NapoleonHomeApiClientError: For any other unexpected exception.

        """
        try:
            async with asyncio.timeout(10):
                response = await self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json,
                )
                _verify_response_or_raise(response)
                return await response.json()

        except TimeoutError as exception:
            msg = f"Timeout error fetching information - {exception}"
            raise NapoleonHomeApiClientCommunicationError(
                msg,
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error fetching information - {exception}"
            raise NapoleonHomeApiClientCommunicationError(
                msg,
            ) from exception
        except NapoleonHomeApiClientError:
            raise
        except Exception as exception:
            msg = f"Something really wrong happened! - {exception}"
            raise NapoleonHomeApiClientError(
                msg,
            ) from exception
