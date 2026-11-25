"""The parcel contract's checks, run over every normalised sample."""

from datetime import datetime

import pytest

from custom_components.fan_courier.const import ParcelStatus
from custom_components.fan_courier.parcels import (
    _EVENT_TZ,
    normalize_parcel,
    planned_for_status,
    planned_window,
)

from .payloads import (
    active_sample,
    collected_sample,
    delivered_sample,
    event,
    pickup_sample,
)

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def _returning() -> dict:
    sample = active_sample()
    sample["returnAwbNumber"] = "7000000000000"
    return sample


def _problem() -> dict:
    sample = active_sample()
    sample["events"].append(event("S4", "2025-08-05 10:00:00", "Adresa gresita"))
    return sample


def _returning_from_point() -> dict:
    sample = pickup_sample()
    sample["returnAwbNumber"] = "7000000000000"
    return sample


SAMPLES = {
    "delivered": delivered_sample,
    "active": active_sample,
    "at_pickup_point": pickup_sample,
    "collected": collected_sample,
    "returning": _returning,
    "returning_from_point": _returning_from_point,
    "problem": _problem,
    "bare": lambda: {"trackingNumber": "7000138347299"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_is_empty_without_an_estimate(parcel):
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_collected_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(collected_sample())
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2025-08-06T10:00:00+03:00"
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Easybox Central"


def test_a_returning_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(_returning_from_point())
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["pickup"] is True


def test_a_home_delivery_is_not_pickup():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_pickup_point_is_the_newest_pickup_event_location():
    sample = collected_sample()
    sample["events"].append(
        event("S46", "2025-08-05 18:00:00", "Predat la punct", "Fanbox Nord")
    )
    assert normalize_parcel(sample)["pickup_point"] == "Fanbox Nord"


def test_a_moment_ends_at_the_end_of_that_day():
    start, end = planned_window("2099-04-29T13:00:00+03:00", None, zone=_EVENT_TZ)
    stop = datetime.fromisoformat(end)
    assert start == "2099-04-29T13:00:00+03:00"
    assert (stop.hour, stop.minute, stop.second) == (23, 59, 59)
    assert stop.date() == datetime.fromisoformat(start).date()


def test_a_date_covers_the_whole_day():
    start, end = planned_window("2099-04-29", None, zone=_EVENT_TZ)
    assert datetime.fromisoformat(start).time().isoformat() == "00:00:00"
    assert datetime.fromisoformat(end).time().isoformat() == "23:59:59"


def test_the_window_is_emptied_once_the_parcel_is_done():
    window = ("2099-04-29T00:00:00+03:00", "2099-04-29T23:59:59+03:00")
    for status in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert planned_for_status(status, *window) == (None, None)
    assert planned_for_status(ParcelStatus.IN_TRANSIT, *window) == window


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (
            "2099-04-29T10:00:00+03:00",
            "2099-04-29T12:00:00+03:00",
            ("2099-04-29T10:00:00+03:00", "2099-04-29T12:00:00+03:00"),
        ),
        (
            "2099-04-29T12:00:00+03:00",
            "2099-04-29T10:00:00+03:00",
            ("2099-04-29T10:00:00+03:00", "2099-04-29T12:00:00+03:00"),
        ),
        (
            "2099-04-29T10:00:00+03:00",
            "2099-04-29T10:00:00+03:00",
            ("2099-04-29T10:00:00+03:00", "2099-04-29T23:59:59+03:00"),
        ),
        (
            "2099-04-29",
            "2099-05-01",
            ("2099-04-29T00:00:00+03:00", "2099-05-01T23:59:59+03:00"),
        ),
        (
            "2099-04-29T23:59:59+03:00",
            None,
            ("2099-04-29T23:59:59+03:00", None),
        ),
        (
            "2099-04-29T22:30:00Z",
            None,
            ("2099-04-29T22:30:00Z", "2099-04-30T23:59:59+03:00"),
        ),
        (
            "2099-04-29T10:00:00",
            None,
            ("2099-04-29T10:00:00+03:00", "2099-04-29T23:59:59+03:00"),
        ),
        (
            None,
            "2099-04-29",
            ("2099-04-29T00:00:00+03:00", "2099-04-29T23:59:59+03:00"),
        ),
        ("garbage", None, (None, None)),
        (12345, None, (None, None)),
        (None, None, (None, None)),
    ],
)
def test_planned_window_shapes(start, end, expected):
    assert planned_window(start, end, zone=_EVENT_TZ) == expected
