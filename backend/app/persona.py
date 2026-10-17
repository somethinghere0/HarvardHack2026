from __future__ import annotations

import logging
import random
import secrets
from dataclasses import asdict, dataclass

import httpx

log = logging.getLogger("persona")

_FIRST = ["James", "Maria", "Robert", "Linda", "Michael", "Susan", "David", "Karen"]
_LAST = ["Walker", "Nguyen", "Patel", "Hughes", "Morales", "Bennett", "Foster", "Reyes"]
_STREETS = ["Maple Ave", "Oak St", "Cedar Ln", "Elm Dr", "Lakeview Rd"]
_CITIES = [("Boston", "MA", "02108"), ("Austin", "TX", "78701"), ("Denver", "CO", "80202")]


def _luhn_card(prefix: str = "400000") -> str:
    """Luhn-valid number in a reserved test range (400000...), so it can't be a live customer's card."""
    digits = [int(c) for c in prefix] + [random.randrange(10) for _ in range(15 - len(prefix))]
    total = sum(d * 2 - 9 if d * 2 > 9 else d * 2 for d in digits[::-2]) + sum(digits[-2::-2])
    return "".join(map(str, digits)) + str((10 - total % 10) % 10)


@dataclass
class Persona:
    canary: str  # unique per scam; any later reuse of these values traces back to this message
    first_name: str
    last_name: str
    name: str
    email: str
    phone: str
    street: str
    address: str
    city: str
    state: str
    zip: str
    username: str
    password: str
    card: str
    cvv: str
    expiry: str
    ssn: str
    routing: str
    account: str
    pin: str
    otp: str
    nessie_customer_id: str | None = None

    def for_sandbox(self) -> dict:
        d = asdict(self)
        d.pop("nessie_customer_id")
        return d


def generate(canary_email_base: str = "") -> Persona:
    canary = secrets.token_hex(4)
    first, last = random.choice(_FIRST), random.choice(_LAST)
    city, state, zip_ = random.choice(_CITIES)
    street = f"{random.randint(10, 999)} {random.choice(_STREETS)}"
    if "@" in canary_email_base:
        local, domain = canary_email_base.split("@", 1)
        email = f"{local}+{canary}@{domain}"  # plus-address: replies land in the monitored mailbox
    else:
        email = f"{first.lower()}.{last.lower()}.{canary}@canary.invalid"
    return Persona(
        canary=canary, first_name=first, last_name=last, name=f"{first} {last}", email=email,
        phone=f"555{random.randint(2000000, 9999999)}", street=street, address=street, city=city, state=state,
        zip=zip_, username=f"{first.lower()}{last.lower()}{canary[:4]}", password=secrets.token_urlsafe(10) + "A1!",
        card=_luhn_card(), cvv=f"{random.randint(100, 999)}", expiry="08/29",
        ssn=f"900-{random.randint(10, 99)}-{random.randint(1000, 9999)}",  # 9xx area numbers are never issued
        routing="000000000", account=str(random.randint(10**9, 10**10 - 1)), pin=f"{random.randint(1000, 9999)}",
        otp=f"{random.randint(100000, 999999)}",
    )


class PersonaFactory:
    """Creates decoy personas; when a proxy login is configured, also registers a matching Nessie customer and
    account so the persona has a real (simulated) bank behind it. Failures never block detonation."""

    def __init__(self, proxy_url: str, username: str = "", password: str = "", canary_email_base: str = "",
                 transport: httpx.AsyncBaseTransport | None = None):
        self.proxy_url, self.username, self.password = proxy_url.rstrip("/"), username, password
        self.canary_email_base = canary_email_base
        self._transport = transport
        self._token = ""

    async def _login(self, http: httpx.AsyncClient) -> str:
        r = await http.post("/auth/login", json={"username": self.username, "password": self.password})
        if r.status_code == 401:
            r = await http.post("/auth/signup", json={
                "username": self.username, "password": self.password, "first_name": "Gateway", "last_name": "Service",
                "address": {"street_number": "1", "street_name": "Main St", "city": "Boston", "state": "MA", "zip": "02108"}})
        r.raise_for_status()
        return r.json()["token"]

    async def new(self) -> Persona:
        p = generate(self.canary_email_base)
        if not (self.username and self.password):
            return p
        try:
            async with httpx.AsyncClient(base_url=self.proxy_url, timeout=20, transport=self._transport) as http:
                self._token = self._token or await self._login(http)
                auth = {"Authorization": f"Bearer {self._token}"}
                r = await http.post("/customers", headers=auth, json={
                    "first_name": p.first_name, "last_name": p.last_name,
                    "address": {"street_number": p.street.split()[0], "street_name": p.street.split(" ", 1)[1],
                                "city": p.city, "state": p.state, "zip": p.zip}})
                r.raise_for_status()
                p.nessie_customer_id = r.json().get("objectCreated", r.json()).get("_id") or r.json().get("id")
                if p.nessie_customer_id:
                    await http.post(f"/customers/{p.nessie_customer_id}/accounts", headers=auth, json={
                        "type": "Checking", "nickname": "Primary Checking", "rewards": 0,
                        "balance": random.randint(2000, 9000), "account_number": p.account.zfill(16)})
        except Exception as e:  # persona still works with local data
            self._token = ""
            log.warning("could not register persona with Nessie via proxy: %s", type(e).__name__)
        return p
