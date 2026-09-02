"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

Two things here are carrier-specific and marked ``TODO(carrier)``:
:data:`_STATUS_MAP` and :func:`normalize_parcel`. Everything else — the
timestamp parsing, the history builder, the sort contract, the delivered
filter, the one-shot warning for unmapped statuses — is suite-wide machinery
and should be left alone.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-fan-courier/issues/new"
    "?template=unrecognised_status.yml"
)

# TODO(carrier): map the carrier's own status vocabulary onto ParcelStatus.
#
# The keys are whatever the API reports; the values must come from the
# canonical enum — never invent a new one. Prefer mapping too little over
# mapping wrongly: an unmapped value surfaces as ``unknown`` plus a one-shot
# warning that asks the user to report it, which is how the map grows.
_STATUS_MAP: dict[str, ParcelStatus] = {
    "C0": ParcelStatus.REGISTERED,
    "H0": ParcelStatus.IN_TRANSIT,
    "H1": ParcelStatus.IN_TRANSIT,
    "H3": ParcelStatus.IN_TRANSIT,
    "H4": ParcelStatus.IN_TRANSIT,
    "H10": ParcelStatus.IN_TRANSIT,
    "H11": ParcelStatus.IN_TRANSIT,
    "C1": ParcelStatus.OUT_FOR_DELIVERY,
    "S1": ParcelStatus.OUT_FOR_DELIVERY,
    "S2": ParcelStatus.DELIVERED,
    "S3": ParcelStatus.PROBLEM,
    "S46": ParcelStatus.AT_PICKUP_POINT,
    "S47": ParcelStatus.IN_TRANSIT,
}

_EVENT_TZ = ZoneInfo("Europe/Bucharest")

_LOCKER_KEYWORDS = (
    "fanbox", "easybox", "locker", "automat de colete", "disponibil pentru ridicare"
)

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised FAN Courier status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a carrier status code to a canonical :class:`ParcelStatus`.

    ``None`` (a not-yet-scanned parcel) reports ``unknown`` silently; an
    unrecognised code reports ``unknown`` with a one-shot warning.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    mapped = _STATUS_MAP.get(code)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(code)
    return ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus | None:
    """Map a history entry's status code to a canonical status, or ``None``.

    A missing code (``None``/empty) keeps ``status: null`` on the history
    entry. A present-but-unmapped code reports ``unknown``, warning once via
    the parcel-status one-shot set — it is never left ``null``.
    """
    return map_parcel_status(code) if code else None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{int(length)} x {int(width)} x {int(height)} cm",
    }


def _event_date(event: dict[str, Any]) -> datetime | None:
    """Parse a FAN event date, assumed Europe/Bucharest local time.

    FAN's event dates carry no UTC offset. Treating them as Bucharest local
    time (rather than UTC) is a deliberate assumption — FAN Courier is a
    Romania-only carrier — not an independently confirmed fact.
    """
    try:
        naive = datetime.strptime(str(event.get("date") or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=_EVENT_TZ)


def _ordered_events(events: list | None) -> list[dict[str, Any]]:
    """Return oldest-first events, with malformed dates retained at the end."""
    return sorted(
        (event for event in events or [] if isinstance(event, dict)),
        key=lambda event: (_event_date(event) is None, _event_date(event) or datetime.max),
    )


def build_history(events: list | None, *, max_events: int = HISTORY_MAX_EVENTS) -> list[dict]:
    """Build FAN history; timestamps assume Europe/Bucharest (see :func:`_event_date`)."""
    result = []
    for event in _ordered_events(events)[-max_events:]:
        parsed = _event_date(event)
        result.append({
            "timestamp": parsed.isoformat() if parsed else None,
            "status": map_event_status(str(event.get("id") or "") or None),
            "raw_status": str(event.get("id") or "") or None,
        })
    return result


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def normalize_parcel(
    raw: dict, *, tracking_code: str | None = None, include_history: bool = False
) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**. Timestamps assume
    Europe/Bucharest local time — see :func:`_event_date`.
    """
    events = _ordered_events(raw.get("events"))
    newest = events[-1] if events else {}
    raw_status = str(newest.get("id") or "") or None
    status = map_parcel_status(raw_status)
    event_name = str(newest.get("name") or "")
    if status is not ParcelStatus.DELIVERED and any(
        keyword in event_name.casefold() for keyword in _LOCKER_KEYWORDS
    ):
        status = ParcelStatus.AT_PICKUP_POINT
    delivered_event = next(
        (event for event in reversed(events) if str(event.get("id") or "") == "S2"), None
    )
    delivered = delivered_event is not None
    if delivered:
        status = ParcelStatus.DELIVERED
    elif raw.get("returnAwbNumber"):
        status = ParcelStatus.RETURNING
    delivered_at = None
    if delivered_event is not None:
        parsed = _event_date(delivered_event)
        delivered_at = parsed.isoformat() if parsed else None
    barcode = tracking_code or raw.get("awbNumber")
    dims = raw.get("dimensions") or {}

    return {
        "carrier": "FAN Courier",
        "barcode": barcode,
        "sender": None,
        "receiver": (raw.get("confirmation") or {}).get("name") or None,
        "status": status,
        "raw_status": raw_status,
        "delivered": delivered,
        "delivered_at": delivered_at,
        "planned_from": None,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": newest.get("location") if status is ParcelStatus.AT_PICKUP_POINT else None,
        "url": tracking_url(barcode),
        "weight": raw.get("weight"),
        "dimensions": format_dimensions(
            dims.get("length"), dims.get("width"), dims.get("height")
        ),
        "history": build_history(events) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(
        CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE
    )
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(timezone.utc) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
