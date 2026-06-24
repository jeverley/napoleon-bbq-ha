"""
Ayla cloud API client for napoleon_home.

This module provides the HTTP client used during config flow setup to authenticate
with the Ayla IoT cloud and fetch the per-device BLE local key required for the
Ayla Local Control v2 handshake.

After initial setup the local key is stored in the config entry and the cloud API
is not contacted again. All subsequent communication uses the BLE local key
directly over Bluetooth.

For more information on the Ayla cloud API:
See _handover/CLAUDE.md — Cloud API section.

For more information on creating API clients:
https://developers.home-assistant.io/docs/api_lib_index
"""

from __future__ import annotations

import asyncio
import socket
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

    Used once at config flow setup time to authenticate the user with the Ayla
    IoT cloud, discover their Napoleon Prestige grill(s), and fetch the per-device
    BLE local key. After setup, the local key is persisted in the config entry
    and the cloud API is no longer needed.

    The sign-in flow is a two-step process:
    1. POST to the Ayla user API with Napoleon app credentials and the user's
       Napoleon account email and password to obtain an access token.
    2. GET the device connection config from the Ayla device API using the
       device DSN to obtain the local_key.

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
    ) -> tuple[str, str]:
        """
        Sign in to the Ayla cloud and return the DSN and local key for a Napoleon grill.

        If a DSN is provided the local key is fetched for that specific device.
        Otherwise, the user's device list is queried and the first Napoleon Prestige
        grill matching the region's OEM model is used.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.
            dsn: Optional device serial number. Auto-discovered from the Ayla
                device list when not provided.

        Returns:
            A tuple of ``(dsn, local_key)`` where ``dsn`` is the Ayla device serial
            number and ``local_key`` is the base64-encoded BLE authentication key.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If sign-in fails due to invalid
                credentials (HTTP 401/403).
            NapoleonHomeApiClientCommunicationError: If a network or timeout error
                occurs while contacting the Ayla cloud.
            NapoleonHomeApiClientError: If no Napoleon Prestige grill is found in the
                user's Ayla account.

        """
        access_token = await self._async_sign_in(username, password)
        if dsn is None:
            devices = await self._async_list_devices(access_token)
            if not devices:
                msg = f"No Napoleon Prestige grill found in Ayla account (expected OEM model '{self._region.prestige_oem_model}')"
                raise NapoleonHomeApiClientError(msg)
            dsn = devices[0][0]
        local_key = await self._async_fetch_local_key(access_token, dsn)
        return dsn, local_key

    async def async_list_devices(
        self,
        username: str,
        password: str,
    ) -> list[tuple[str, str]]:
        """
        Sign in and return all Napoleon grills in the account matching this region.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.

        Returns:
            A list of ``(dsn, display_name)`` tuples for every matching grill found.
            Returns an empty list if the account has no matching devices.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If sign-in fails.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        access_token = await self._async_sign_in(username, password)
        return await self._async_list_devices(access_token)

    async def async_refresh_local_keys(
        self,
        username: str,
        password: str,
        dsns: list[str],
    ) -> list[str]:
        """
        Sign in once and fetch fresh local keys for the given list of DSNs.

        Used during reauthentication to refresh all sub-entries in a single
        sign-in round-trip.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.
            dsns: List of Ayla device serial numbers to refresh.

        Returns:
            A list of local key strings in the same order as ``dsns``.

        Raises:
            NapoleonHomeApiClientAuthenticationError: If sign-in fails.
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        access_token = await self._async_sign_in(username, password)
        return list(await asyncio.gather(*[self._async_fetch_local_key(access_token, dsn) for dsn in dsns]))

    async def _async_sign_in(self, username: str, password: str) -> str:
        """
        Authenticate with the Ayla user API and return an access token.

        Posts to ``/users/sign_in.json`` with the Napoleon application credentials
        and the user's account email and password.

        Args:
            username: Napoleon app account email address.
            password: Napoleon app account password.

        Returns:
            The Ayla access token string.

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
        return access_token

    async def _async_list_devices(self, access_token: str) -> list[tuple[str, str]]:
        """
        List all Napoleon Prestige grills in the account and return their DSN and name.

        Queries ``/apiv1/devices.json`` and filters by the OEM model string defined
        in the region configuration.

        Args:
            access_token: A valid Ayla access token from ``_async_sign_in``.

        Returns:
            A list of ``(dsn, display_name)`` tuples for each matching grill.

        Raises:
            NapoleonHomeApiClientCommunicationError: On network errors.

        """
        url = f"https://{self._region.device_host}/apiv1/devices.json"
        headers = {"Authorization": f"auth_token {access_token}"}
        data = await self._api_wrapper(method="get", url=url, headers=headers)

        prestige_model = self._region.prestige_oem_model
        devices: list[tuple[str, str]] = []
        for entry in data:
            device = entry.get("device", {})
            if device.get("oem_model") == prestige_model:
                dsn: str = device["dsn"]
                name: str = device.get("friendly_name") or device.get("product_name") or dsn
                LOGGER.debug("Found Napoleon Prestige grill: DSN=%s name=%r", dsn, name)
                devices.append((dsn, name))
        return devices

    async def _async_fetch_local_key(self, access_token: str, dsn: str) -> str:
        """
        Fetch the BLE local key for a specific Ayla device DSN.

        Queries ``/apiv1/devices/{dsn}/connection_config.json`` and returns the
        ``data.local_key`` field from the response.

        Args:
            access_token: A valid Ayla access token from ``_async_sign_in``.
            dsn: The Ayla device serial number.

        Returns:
            The base64-encoded local key string used for BLE authentication.

        Raises:
            NapoleonHomeApiClientAuthenticationError: On 401/403 responses.
            NapoleonHomeApiClientCommunicationError: On network errors or timeouts.

        """
        url = f"https://{self._region.device_host}/apiv1/devices/{dsn}/connection_config.json"
        headers = {"Authorization": f"auth_token {access_token}"}
        data = await self._api_wrapper(method="get", url=url, headers=headers)
        local_key: str = data["local_key"]
        return local_key

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
