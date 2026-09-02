"""Redacted FAN Courier-shaped responses."""

ACTIVE_CODE = "7000138347202"
DELIVERED_CODE = "7000138347203"


def event(code: str, date: str, name: str, location: str = "Bucuresti") -> dict:
    return {"id": code, "date": date, "name": name, "location": location}


def active_sample(code: str = ACTIVE_CODE) -> dict:
    return {
        "awbNumber": code, "trackingNumber": code, "weight": 5,
        "confirmation": {"name": "REDACTED", "date": "2025-08-05 12:00:00"},
        "returnAwbNumber": None,
        "dimensions": {"length": 20, "width": 20, "height": 10},
        "events": [event("C0", "2025-08-04 08:00:00", "Expeditie ridicata"), event("C1", "2025-08-05 08:00:00", "In livrare")],
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    sample = active_sample(code)
    sample["events"].append(event("S2", "2025-08-05 12:00:00", "Livrat"))
    return sample


def pickup_sample() -> dict:
    sample = active_sample()
    sample["events"].append(event("H4", "2025-08-05 12:00:00", "Disponibil pentru ridicare", "Easybox Central"))
    return sample
