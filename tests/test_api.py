"""Tests for the public FAN Courier transport."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.fan_courier.api import FANCourierApiClient, FANCourierApiError


def _session(status: int, body: object) -> MagicMock:
    response = AsyncMock()
    response.status = status
    response.headers = {}
    response.json = AsyncMock(
        side_effect=json.JSONDecodeError("x", str(body), 0) if isinstance(body, str) else None,
        return_value=None if isinstance(body, str) else body,
    )
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post.return_value = context
    return session


async def test_posts_only_the_public_form_fields():
    session = _session(200, {"awbNumber": "700", "events": []})
    assert await FANCourierApiClient(session).async_get_parcel("700") == {"awbNumber": "700", "events": []}
    assert session.post.call_args.kwargs["data"] == {"action": "get_awb", "awb": "700", "lang": "romana"}


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"error": "x"},
        # Confirmed live against a real invalid AWB (2026-09-02):
        # POST awb=XYZINVALIDNOTAREALCODE999 -> exactly this shape.
        {"awbNumber": None, "message": "AWB-ul nu a fost gasit."},
        [],
    ],
)
async def test_not_found_shapes_return_none(body):
    assert await FANCourierApiClient(_session(200, body)).async_get_parcel("700") is None


async def test_unwraps_single_item_list():
    parcel = await FANCourierApiClient(_session(200, [{"awbNumber": "700", "events": []}])).async_get_parcel("700")
    assert parcel["awbNumber"] == "700"


@pytest.mark.parametrize("status,body", [(500, {}), (200, [{"events": []}, {"events": []}]), (200, {"awbNumber": "700"}), (200, "html")])
async def test_bad_responses_fail(status, body):
    with pytest.raises(FANCourierApiError):
        await FANCourierApiClient(_session(status, body)).async_get_parcel("700")


async def test_429_carries_status_code():
    with pytest.raises(FANCourierApiError) as error:
        await FANCourierApiClient(_session(429, {})).async_get_parcel("700")
    assert error.value.status_code == 429


async def test_network_error_propagates():
    session = MagicMock()
    session.post.side_effect = aiohttp.ClientError()
    with pytest.raises(aiohttp.ClientError):
        await FANCourierApiClient(session).async_get_parcel("700")
