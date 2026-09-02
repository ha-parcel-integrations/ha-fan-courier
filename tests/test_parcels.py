"""FAN-specific normalisation tests."""
import pytest

from custom_components.fan_courier.const import CAPABILITIES, ParcelStatus
from custom_components.fan_courier.parcels import (
    build_history,
    map_parcel_status,
    normalize_parcel,
)

from .payloads import active_sample, delivered_sample, pickup_sample


@pytest.mark.parametrize(
    ("code", "status"),
    [("C0", ParcelStatus.REGISTERED), ("H0", ParcelStatus.IN_TRANSIT), ("H1", ParcelStatus.IN_TRANSIT), ("H3", ParcelStatus.IN_TRANSIT), ("H4", ParcelStatus.IN_TRANSIT), ("H10", ParcelStatus.IN_TRANSIT), ("H11", ParcelStatus.IN_TRANSIT), ("C1", ParcelStatus.OUT_FOR_DELIVERY), ("S1", ParcelStatus.OUT_FOR_DELIVERY), ("S2", ParcelStatus.DELIVERED), ("S3", ParcelStatus.PROBLEM), ("S46", ParcelStatus.AT_PICKUP_POINT), ("S47", ParcelStatus.IN_TRANSIT)],
)
def test_maps_evidenced_codes(code, status):
    assert map_parcel_status(code) is status


def test_unknown_code_warns_and_falls_back(caplog):
    assert map_parcel_status("NEW") is ParcelStatus.UNKNOWN
    assert "issues/new" in caplog.text


def test_normalizes_latest_event_and_deeplink():
    parcel = normalize_parcel(active_sample())
    assert parcel["status"] is ParcelStatus.OUT_FOR_DELIVERY
    assert parcel["raw_status"] == "C1"
    assert parcel["barcode"] == "7000138347202"
    assert parcel["url"] == "https://www.fancourier.ro/awb-tracking/?tracking=7000138347202"
    assert parcel["weight"] == 5
    assert parcel["dimensions"] == {"length": 20, "width": 20, "height": 10, "text": "20 x 20 x 10 cm"}
    assert parcel["sender"] is None
    assert parcel["receiver"] == "REDACTED"
    assert parcel["raw"] is not None


def test_missing_confirmation_leaves_receiver_none():
    raw = active_sample()
    del raw["confirmation"]
    assert normalize_parcel(raw)["receiver"] is None


def test_missing_weight_and_dimensions_stay_none():
    raw = active_sample()
    del raw["weight"]
    del raw["dimensions"]
    parcel = normalize_parcel(raw)
    assert parcel["weight"] is None
    assert parcel["dimensions"] is None


def test_delivery_timestamp_assumes_bucharest_local_time():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2025-08-05T12:00:00+03:00"


def test_delivered_at_none_without_a_delivered_event():
    assert normalize_parcel(active_sample())["delivered_at"] is None


def test_locker_event_sets_pickup_point_and_keeps_payload():
    parcel = normalize_parcel(pickup_sample())
    assert parcel["status"] is ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup_point"] == "Easybox Central"
    assert parcel["pickup"] is True
    assert parcel["raw"]["events"][-1]["location"] == "Easybox Central"


def test_non_pickup_parcel_has_pickup_false():
    assert normalize_parcel(active_sample())["pickup"] is False


def test_return_overrides_non_delivered_status():
    raw = active_sample()
    raw["returnAwbNumber"] = "7000000000000"
    assert normalize_parcel(raw)["status"] is ParcelStatus.RETURNING


def test_history_is_ordered_with_bucharest_timestamps():
    history = build_history(list(reversed(active_sample()["events"])))
    assert [entry["raw_status"] for entry in history] == ["C0", "C1"]
    assert [entry["timestamp"] for entry in history] == [
        "2025-08-04T08:00:00+03:00",
        "2025-08-05T08:00:00+03:00",
    ]


def test_history_timestamp_none_for_unparseable_date():
    history = build_history([{"id": "C0", "date": "not-a-date"}])
    assert history[0]["timestamp"] is None


def test_history_is_opt_in_and_capabilities_are_true():
    assert normalize_parcel(active_sample())["history"] is None
    assert normalize_parcel(active_sample(), include_history=True)["history"]
    assert CAPABILITIES == {"weight", "dimensions", "pickup_point", "url", "history"}
