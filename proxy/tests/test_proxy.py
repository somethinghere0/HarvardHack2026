import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SIGNUP = {
    "username": "Alice", "password": "correct horse", "first_name": "Alice", "last_name": "Ng",
    "address": {"street_number": "1", "street_name": "Main St", "city": "McLean", "state": "VA", "zip": "22101"},
}
seen = []


def nessie_handler(request: httpx.Request) -> httpx.Response:
    seen.append(request)
    if request.method == "POST" and request.url.path == "/customers":
        return httpx.Response(201, json={"id": "cust_1"})
    return httpx.Response(200, json={"path": request.url.path, "q": request.url.query.decode()},
                          headers={"RateLimit-Remaining": "119"})


@pytest.fixture
def client(tmp_path):
    seen.clear()
    s = Settings(nessie_api_key="nsk_secret", db_path=str(tmp_path / "t.db"), auth_rate_limit=100)
    with TestClient(create_app(s, httpx.MockTransport(nessie_handler))) as c:
        yield c


def signup(c, **over):
    return c.post("/auth/signup", json={**SIGNUP, **over})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_creates_customer_and_session(client):
    r = signup(client)
    assert r.status_code == 201 and r.json()["customer_id"] == "cust_1"
    assert client.get("/auth/me", headers=auth(r.json()["token"])).json() == {"username": "alice", "customer_id": "cust_1"}


def test_duplicate_username_is_409_and_creates_no_customer(client):
    signup(client)
    n = len(seen)
    assert signup(client, username="ALICE").status_code == 409
    assert len(seen) == n


def test_signup_validation(client):
    assert signup(client, password="short").status_code == 422
    assert signup(client, address={**SIGNUP["address"], "zip": "abc"}).status_code == 422


def test_login_and_logout(client):
    signup(client)
    assert client.post("/auth/login", json={"username": "alice", "password": "wrong"}).status_code == 401
    assert client.post("/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401
    token = client.post("/auth/login", json={"username": "ALICE", "password": "correct horse"}).json()["token"]
    assert client.post("/auth/logout", headers=auth(token)).status_code == 204
    assert client.get("/auth/me", headers=auth(token)).status_code == 401


def test_proxy_requires_session(client):
    assert client.get("/accounts").status_code == 401
    assert client.get("/accounts", headers=auth("bogus")).status_code == 401
    assert not seen


def test_proxy_forwards_with_server_key_only(client):
    token = signup(client).json()["token"]
    seen.clear()
    r = client.get("/accounts?limit=5", headers=auth(token))
    assert r.status_code == 200 and r.json() == {"path": "/accounts", "q": "limit=5"}
    assert r.headers["RateLimit-Remaining"] == "119"
    assert seen[0].headers["authorization"] == "Bearer nsk_secret"
    assert token not in str(seen[0].headers)


def test_login_rate_limit(tmp_path):
    s = Settings(nessie_api_key="k", db_path=str(tmp_path / "t.db"), auth_rate_limit=3)
    with TestClient(create_app(s, httpx.MockTransport(nessie_handler))) as c:
        codes = [c.post("/auth/login", json={"username": "a", "password": "b"}).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


# --- honeypot telemetry: who signed in, the transfer-limit tripwire, contact changes ------------

def _orch_capture(monkeypatch):
    """Capture the proxy's best-effort posts to the orchestrator instead of making them."""
    import app.auth_routes as ar
    import app.proxy as px
    sent = []

    async def post(request, path, body):
        sent.append((path.rsplit("/", 1)[-1], body))

    async def tell(request, user, type_, data):
        sent.append(("event", {"username": user["username"], "type": type_, "data": {**px._who(request, user), **data}}))

    async def log(request, user, path, status):
        sent.append(("proxy-log", {"path": path, "status": status}))

    monkeypatch.setattr(ar, "_orchestrator_post", post)
    monkeypatch.setattr(px, "_tell", tell)
    monkeypatch.setattr(px, "_log_request", log)
    return sent


def _telemetry_client(tmp_path, monkeypatch, **over):
    sent = _orch_capture(monkeypatch)
    s = Settings(nessie_api_key="k", db_path=str(tmp_path / "t.db"), auth_rate_limit=100,
                 orchestrator_url="http://orch", **over)
    return TestClient(create_app(s, httpx.MockTransport(nessie_handler))), sent


def test_login_actor_is_agent_only_with_marker_header(tmp_path, monkeypatch):
    c, sent = _telemetry_client(tmp_path, monkeypatch)
    with c:
        signup(c)
        sent.clear()
        c.post("/auth/login", json={"username": "alice", "password": "correct horse"}, headers={"X-Decoy-Agent": "e1"})
        c.post("/auth/login", json={"username": "alice", "password": "correct horse"},
               headers={"User-Agent": "Mozilla/5.0 (Macintosh) Chrome/129"})
        c.post("/auth/login", json={"username": "alice", "password": "nope"})
    kinds = [(j["type"], j["data"]["actor"]) for k, j in sent if k == "event"]
    assert kinds == [("login.password_ok", "agent"), ("session.login", "agent"),
                     ("login.password_ok", "external"), ("session.login", "external"),
                     ("login.failed", "external")]
    ext = next(j for k, j in sent if j.get("type") == "session.login" and j["data"]["actor"] == "external")
    assert ext["data"]["sid"].startswith("s_") and "Chrome" in ext["data"]["ua"]


def test_transfer_limit_declines_and_reports(tmp_path, monkeypatch):
    c, sent = _telemetry_client(tmp_path, monkeypatch, transfer_limit_cents=500000)
    with c:
        token = signup(c).json()["token"]
        sent.clear()
        seen.clear()
        big = c.post("/accounts/acct_1/transfers", json={"payee_id": "acct_m", "amount_cents": 700000}, headers=auth(token))
        ok = c.post("/accounts/acct_1/transfers", json={"payee_id": "acct_m", "amount_cents": 480000}, headers=auth(token))
    assert big.status_code == 422 and big.json()["type"] == "transfer_limit_exceeded"
    assert ok.status_code == 200
    types = [j["type"] for k, j in sent if k == "event"]
    assert types == ["transfer.declined", "money.attempt"]
    assert [j["status"] for k, j in sent if k == "proxy-log"] == [422, 200]
    declined = next(j for k, j in sent if j.get("type") == "transfer.declined")["data"]
    assert declined["amount_cents"] == 700000 and declined["limit_cents"] == 500000 and declined["actor"] == "external"
    attempt = next(j for k, j in sent if j.get("type") == "money.attempt")["data"]
    assert attempt["kind"] == "transfer" and attempt["payee_id"] == "acct_m" and attempt["status"] == "accepted"
    # Only one upstream POST reached Nessie: the one under the limit.
    posts = [r for r in seen if r.method == "POST" and r.url.path.endswith("/transfers")]
    assert len(posts) == 1


def test_profile_change_is_reported_with_before_and_after(tmp_path, monkeypatch):
    c, sent = _telemetry_client(tmp_path, monkeypatch)
    with c:
        token = signup(c, email="alice@example.test", phone="555-0100").json()["token"]
        assert c.get("/auth/profile", headers=auth(token)).json()["email"] == "alice@example.test"
        sent.clear()
        r = c.patch("/auth/profile", json={"email": "drop@evil.test"}, headers=auth(token))
        same = c.patch("/auth/profile", json={"email": "drop@evil.test"}, headers=auth(token))
    assert r.json()["changed"] == ["email"] and same.json()["changed"] == []
    ev = [j for k, j in sent if k == "event"]
    assert len(ev) == 1 and ev[0]["type"] == "contact.changed"
    assert ev[0]["data"]["changes"]["email"] == {"from": "alice@example.test", "to": "drop@evil.test"}
