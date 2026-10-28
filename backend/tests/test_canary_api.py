"""The orchestrator's canary end to end over HTTP (no Nessie, no proxy): a scam verdict leaves the
engagement ARMED; a sign-in reported by the proxy without the agent marker confirms it, re-grades the
inbox message, and the intel endpoints reflect the mule and the decision hook's verdicts."""
import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SECRET = "test-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCH_DB_PATH", str(tmp_path / "orch.db"))
    monkeypatch.setenv("NESSIE_API_KEY", "nsk_test")
    monkeypatch.setenv("NESSIE_BASE_URL", "http://127.0.0.1:9")  # nothing listens: startup falls back to polling
    monkeypatch.setenv("INTERNAL_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_URL", "")
    for m in ("app.config", "app.main"):
        sys.modules.pop(m, None)
    main = importlib.import_module("app.main")
    with TestClient(main.app) as c:
        yield c, main


def _seed_scam(main, eid="e1", mule="acct_mule"):
    db = main.db
    path = main.s.db_path
    db.create_engagement(path, eid, "email", "scammer@x.test", "URGENT")
    msg_id = db.add_message(path, {"sender": "scammer@x.test", "subject": "URGENT", "body": "...", "verdict": "pending",
                                   "action": "held", "engagement_id": eid})
    db.create_persona(path, {"id": "p" + eid, "engagement_id": eid, "username": "jane.doe42", "password": "pw",
                             "email": "x+persona@gmail.com", "customer_id": "c1", "first_name": "Jane", "last_name": "Doe"})
    db.add_event(path, eid, "system", "persona.created", {"persona_id": "p" + eid, "customer_id": "c1",
                                                          "username": "jane.doe42", "accounts": ["acct_chk", "acct_sav"]})
    db.add_event(path, eid, "proxy", "session.login", {"actor": "agent", "sid": "s_agent", "ip": "10.0.0.5"})
    db.add_event(path, eid, "nessie", "transfer.created", {"tx_id": "txn_1", "payer_id": "acct_chk", "payee_id": mule, "amount_cents": 310000})
    db.add_event(path, eid, "agent", "agent.finished", {"summary": "moved it", "complied": True})
    return msg_id


def test_scam_is_armed_then_confirmed_by_outside_login(client):
    c, main = client
    msg_id = _seed_scam(main)
    v = main._record_verdict("e1", msg_id)
    assert v["verdict"] == "scam" and v["grade"] == "likely"
    eng = c.get("/engagements/e1").json()
    assert eng["engagement"]["status"] == "armed" and eng["engagement"]["armed"] == 1
    assert eng["decoy"]["username"] == "jane.doe42" and eng["playbook"]["third_party"] is False
    msg = next(m for m in c.get("/messages").json()["messages"] if m["id"] == msg_id)
    assert msg["verdict"] == "scam" and msg["grade"] == "likely"

    # The proxy reports a sign-in that is NOT the agent's: the scammer is back.
    hdr = {"X-Internal-Secret": SECRET}
    r = c.post("/internal/event", json={"username": "jane.doe42", "type": "login.password_ok", "source": "proxy",
                                        "data": {"actor": "external", "ip": "203.0.113.9", "ua": "Mozilla/5.0 Chrome/129"}}, headers=hdr)
    assert r.json()["ok"]
    c.post("/internal/event", json={"username": "jane.doe42", "type": "session.login", "source": "proxy",
                                    "data": {"actor": "external", "sid": "s_bad", "ip": "203.0.113.9", "ua": "Mozilla/5.0 Chrome/129"}}, headers=hdr)
    eng = c.get("/engagements/e1").json()
    assert eng["engagement"]["status"] == "confirmed" and eng["engagement"]["grade"] == "confirmed"
    canaries = [e for e in eng["events"] if e["type"] == "credential.used_by_third_party"]
    assert [x["data"]["stage"] for x in canaries] == ["password", "session"]
    assert "third_party_login" in eng["engagement"]["tags"]
    assert eng["playbook"]["third_party"] and eng["playbook"]["subject"] == "s_bad"
    msg = next(m for m in c.get("/messages").json()["messages"] if m["id"] == msg_id)
    assert msg["grade"] == "confirmed" and msg["reason"].startswith("Confirmed by the outside world")

    # A second identical report doesn't double-count the canary.
    c.post("/internal/event", json={"username": "jane.doe42", "type": "session.login", "source": "proxy",
                                    "data": {"actor": "external", "sid": "s_bad", "ip": "203.0.113.9"}}, headers=hdr)
    assert len([e for e in c.get("/engagements/e1").json()["events"] if e["type"] == "credential.used_by_third_party"]) == 2


def test_agent_login_never_trips_the_canary(client):
    c, main = client
    msg_id = _seed_scam(main)
    main._record_verdict("e1", msg_id)
    c.post("/internal/event", json={"username": "jane.doe42", "type": "session.login", "source": "proxy",
                                    "data": {"actor": "agent", "sid": "s_agent2", "ip": "10.0.0.5"}}, headers={"X-Internal-Secret": SECRET})
    eng = c.get("/engagements/e1").json()
    assert eng["engagement"]["status"] == "armed"
    assert not any(e["type"] == "credential.used_by_third_party" for e in eng["events"])


def test_watchlist_and_decision_hook(client):
    c, main = client
    msg_id = _seed_scam(main)
    main._record_verdict("e1", msg_id)
    wl = c.get("/intel/watchlist").json()
    assert [w["account_id"] for w in wl["watchlist"]] == ["acct_mule"] and wl["screening"] == "poller"

    # Nessie asks about a pending transfer. A decoy draining itself is approved; a customer paying the mule is declined.
    ok = c.post("/webhooks/nessie-decision", json={"type": "transaction.pending", "transaction": {
        "id": "txn_d", "kind": "transfer", "amount_cents": 50000, "payer_id": "acct_chk", "payee_id": "acct_mule"}}).json()
    assert ok == {"decision": "approve"}
    bad = c.post("/webhooks/nessie-decision", json={"type": "transaction.pending", "transaction": {
        "id": "txn_c", "kind": "transfer", "amount_cents": 125000, "payer_id": "acct_customer", "payee_id": "acct_mule"}}).json()
    assert bad["decision"] == "decline" and "e1" in bad["reason"]
    wl = c.get("/intel/watchlist").json()
    assert wl["interdictions"][0]["tx_id"] == "txn_c" and wl["interdictions"][0]["action"] == "declined"
    eng = c.get("/engagements/e1").json()
    assert eng["interdictions"][0]["payer_id"] == "acct_customer"
    assert any(e["type"] == "watchlist.hit" for e in eng["events"])
    assert c.get("/intel/crews").json()["crews"][0]["engagements"] == ["e1"]
