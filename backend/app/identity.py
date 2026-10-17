"""Synthetic persona identities. Uses Photon when configured; otherwise a local generator (Faker if
installed, else a small built-in list). These are entirely fictitious people for the decoy accounts."""
from __future__ import annotations

import random

import httpx

_FIRST = ["Avery", "Jordan", "Riley", "Morgan", "Casey", "Taylor", "Jamie", "Quinn", "Devon", "Harper"]
_LAST = ["Bennett", "Carter", "Dawson", "Ellis", "Foster", "Grant", "Hayes", "Irving", "Jensen", "Keller"]
_STREETS = ["Maple Ave", "Oak St", "Pine Rd", "Cedar Ln", "Birch Blvd", "Elm Way"]
_CITIES = [("Boston", "MA", "02108"), ("Austin", "TX", "73301"), ("Reston", "VA", "20190"),
           ("Denver", "CO", "80202"), ("Tampa", "FL", "33601")]


def _local_identity() -> dict:
    try:
        from faker import Faker  # optional
        f = Faker("en_US")
        return {"first_name": f.first_name(), "last_name": f.last_name(),
                "address": {"street_number": str(f.building_number()), "street_name": f.street_name()[:80],
                            "city": f.city()[:80], "state": f.state_abbr(), "zip": f.zipcode()[:5]}}
    except Exception:
        city, state, zip_ = random.choice(_CITIES)
        return {"first_name": random.choice(_FIRST), "last_name": random.choice(_LAST),
                "address": {"street_number": str(random.randint(1, 9999)), "street_name": random.choice(_STREETS),
                            "city": city, "state": state, "zip": zip_}}


async def generate_identity(s) -> dict:
    """Returns {first_name, last_name, address{...}}."""
    if s.photon_fake or not s.photon_api_key:
        return _local_identity()
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{s.photon_api_url}/identities",
                             headers={"Authorization": f"Bearer {s.photon_api_key}"},
                             json={"locale": "en_US", "type": "person"})
            r.raise_for_status()
            d = r.json()
            return {"first_name": d["first_name"], "last_name": d["last_name"],
                    "address": {"street_number": str(d["address"]["street_number"]),
                                "street_name": d["address"]["street_name"][:80], "city": d["address"]["city"][:80],
                                "state": d["address"]["state"][:2], "zip": str(d["address"]["zip"])[:5]}}
    except Exception:
        return _local_identity()  # never block an engagement on Photon
