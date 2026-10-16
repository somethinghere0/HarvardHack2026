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
