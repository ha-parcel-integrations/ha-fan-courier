"""FAN Courier public tracking API client.

The public form endpoint uses one URL-encoded POST per user-supplied AWB.
Keep the coordinator contract:

* ``async_get_parcel`` returns the raw per-parcel dict on success,
* returns ``None`` when the carrier says the tracking code is unknown or not
  yet scanned (a normal, expected state — never an error),
* raises :class:`FANCourierApiError` for anything else, with
  ``status_code`` set on a non-2xx response and ``retry_after`` set when the
  carrier's own ``Retry-After`` header on a 429 could be parsed as seconds —
  the coordinator's backoff (Section 3 of the dynamic-polling plan) reads
  both,
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)


class FANCourierApiError(Exception):
    """Raised when a FAN Courier API call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"FAN Courier API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class FANCourierApiClient:
    """Client for the public FAN Courier tracking endpoint.

    No authentication: the endpoint is keyed on the tracking code alone.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the parcel dict for a known parcel, or ``None`` when the
        endpoint reports the code as unknown — which is also what a
        not-yet-scanned parcel gets. Any other failure envelope or non-2xx
        status raises :class:`FANCourierApiError`; network errors propagate
        as ``aiohttp.ClientError``.
        """
        form_data = {"action": "get_awb", "awb": tracking_code, "lang": "romana"}
        async with self._session.post(TRACKING_API_URL, data=form_data) as response:
            if response.status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds; let the caller's own backoff handle it
                raise FANCourierApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.status != 200:
                raise FANCourierApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            try:
                # content_type=None: consumer endpoints routinely serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise FANCourierApiError(f"unparseable body ({err})") from err

        if not payload:
            return None
        if isinstance(payload, list):
            if not payload:
                return None
            if len(payload) != 1 or not isinstance(payload[0], dict):
                raise FANCourierApiError("unexpected list response")
            payload = payload[0]
        if not isinstance(payload, dict):
            raise FANCourierApiError("unexpected body")
        if payload.get("error") or (
            "message" in payload and "events" not in payload
        ):
            return None
        if not isinstance(payload.get("events"), list):
            raise FANCourierApiError("success response missing events")
        return payload
