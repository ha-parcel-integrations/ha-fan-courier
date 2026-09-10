# Working in this repository

Home Assistant custom integration for **FAN Courier** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exactly_the_canonical_keys` guards the key set |
| change which optional field this carrier populates vs. always returns `None` | Update `const.py`'s `CAPABILITIES` in the same commit — it feeds the comparison table on the docs site, so a field that starts (or stops) coming back non-null and isn't reflected there is a wrong claim on the website, not just a stale comment. If this carrier has more than one backend (a country-specific transport, not just a config option) with genuinely different field support, `CAPABILITIES` should be a `CAPABILITIES_BY_VARIANT` dict instead — one frozenset per backend, so a field only some backends populate doesn't get silently intersected away or overclaimed for the rest |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Structure, options flow, dynamic polling and module layout are suite-wide**
and identical in every carrier — the authoritative spec is
[`ha-carrier-template/scaffold/CLAUDE.md`](https://github.com/ha-parcel-integrations/ha-carrier-template/blob/main/scaffold/CLAUDE.md).
This repo follows it exactly.

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).
- **If this carrier can reach `ParcelStatus.AT_PICKUP_POINT` from a real raw
  status/code**, it needs an `awaiting_pickup` sensor — see *Parcel contract*
  in `CONVENTIONS.md`. Say "pickup point", not "ServicePoint"/"parcel
  shop"/"locker", for the generic concept. `ha-dhl-nl`, `ha-dpd`, `ha-gls`,
  `ha-inpost` are reference implementations; `fan_courier` reaches
  `AT_PICKUP_POINT` via the `S46` event code and the locker-keyword rule, and
  demonstrates it with its own `awaiting_pickup` sensor.

## Carrier-specific notes

FAN Courier is a keyless, code-based integration. The complete carrier payload
stays under `raw`; diagnostics, logs and HA events recursively redact AWB-like
identifiers, signer data, locations and free event text. `weight` (kilograms)
and `dimensions` (centimetres, via the shared `format_dimensions` helper) come
straight from the response's root-level `weight` and `dimensions` fields —
confirmed against real tracked parcels in production HA on 2026-09-03; a
carrier response can omit `dimensions` entirely, in which case it stays
`None`. `receiver` comes from `confirmation.name` — the delivery signer's
name, which is exactly what the canonical `receiver` field is for elsewhere
in the suite (a plain name string, not a directory/address object); it stays
`None` until a parcel has been signed for. It is already redacted from
diagnostics both as the top-level `receiver` field and inside `raw.confirmation`
(`diagnostics.py`'s `TO_REDACT`) — don't remove either entry. `sender` and
delivery windows intentionally remain `None`: the payload has no sender
field and no ETA. FAN's event dates are naive `YYYY-MM-DD HH:MM:SS` with no
UTC offset; `_event_date()` treats them as **Europe/Bucharest local time** —
a deliberate assumption (FAN Courier is Romania-only), not an independently
confirmed fact — and publishes them with that offset on both
`history[].timestamp` and `delivered_at` (from the newest `S2` event).
`delivered_at` is never derived from `confirmation.date`, which is a
separate, unconfirmed field. Locker-keyword events can expose an
`at_pickup_point` status and
the event location as `pickup_point`. Unknown event codes become `unknown`
and emit a one-shot warning. API mechanics remain in the private
carrier-research notes.

## Running tests

```
python -m pytest tests/ --cov=custom_components.fan_courier
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit; the API reference lives in your own private research notes, never in
this repo.
