"""The attacker playbook, the confidence grade and the watchlist — all pure functions over a synthetic
event timeline. No network."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db, intel, outcome, playbook  # noqa: E402

OWN = ["acct_chk", "acct_sav", "acct_card"]


def _setup(tmp_path, eid="e1"):
    path = str(tmp_path / "orch.db")
    db.init_db(path)
    db.create_engagement(path, eid, "email", "scammer@x.test", "URGENT")
    db.add_event(path, eid, "system", "persona.created",
                 {"persona_id": "p1", "customer_id": "c1", "accounts": OWN,
                  "account_types": {"acct_chk": "Checking", "acct_sav": "Savings", "acct_card": "Credit Card"}})
    return path


def _agent_run(path, eid="e1"):
    db.add_event(path, eid, "proxy", "login.password_ok", {"actor": "agent", "ip": "10.0.0.5", "ua": "HeadlessChrome"})
    db.add_event(path, eid, "proxy", "session.login", {"actor": "agent", "sid": "s_agent", "ip": "10.0.0.5", "ua": "HeadlessChrome"})
    db.add_event(path, eid, "proxy", "money.attempt", {"actor": "agent", "sid": "s_agent", "kind": "transfer",
                                                        "payer_id": "acct_chk", "payee_id": "acct_mule",
                                                        "amount_cents": 310000, "status": "accepted", "tx_id": "txn_1"})
    db.add_event(path, eid, "nessie", "transfer.created", {"tx_id": "txn_1", "payer_id": "acct_chk",
                                                            "payee_id": "acct_mule", "amount_cents": 310000})
    db.add_event(path, eid, "agent", "agent.finished", {"summary": "moved the money", "complied": True})


def test_agent_only_run_is_likely_not_confirmed(tmp_path):
    path = _setup(tmp_path)
    _agent_run(path)
    v = outcome.decide(path, "e1")
    assert v["verdict"] == "scam" and v["grade"] == "likely"
    pb = playbook.analyse(db.list_events(path, "e1"))
    assert pb["third_party"] is False
    assert pb["profile"]["label"] == "decoy compliance"
    assert pb["metrics"]["moved_out_cents"] == 310000 and pb["metrics"]["mules"] == ["acct_mule"]


def test_third_party_login_confirms_and_is_profiled(tmp_path):
    path = _setup(tmp_path)
    _agent_run(path)
    # The scammer comes back from a real browser: recon, lockout, sweep, a refused big transfer, then
    # two structured transfers under the limit.
    ext = {"actor": "external", "sid": "s_bad", "ip": "203.0.113.9", "ua": "Mozilla/5.0 Chrome/129"}
    db.add_event(path, "e1", "proxy", "login.password_ok", {k: v for k, v in ext.items() if k != "sid"})
    db.add_event(path, "e1", "proxy", "session.login", ext)
    db.add_event(path, "e1", "system", "credential.used_by_third_party", {"stage": "session", "sid": "s_bad", "ip": "203.0.113.9"})
    db.add_event(path, "e1", "proxy", "request", {**ext, "method": "GET", "path": "/customers/c1/accounts", "status": 200})
    db.add_event(path, "e1", "proxy", "request", {**ext, "method": "GET", "path": "/accounts/acct_sav/transactions", "status": 200})
    db.add_event(path, "e1", "proxy", "contact.changed", {**ext, "fields": ["email"],
                                                           "changes": {"email": {"from": "a@b", "to": "drop@evil.test"}}})
    db.add_event(path, "e1", "proxy", "money.attempt", {**ext, "kind": "transfer", "payer_id": "acct_sav", "payee_id": "acct_chk",
                                                         "amount_cents": 400000, "status": "accepted", "tx_id": "txn_2"})
    db.add_event(path, "e1", "proxy", "transfer.declined", {**ext, "kind": "transfer", "payer_id": "acct_chk", "payee_id": "acct_mule",
                                                             "amount_cents": 700000, "limit_cents": 500000, "reason": "transfer_limit_exceeded"})
    for i, amt in enumerate((480000, 470000)):
        db.add_event(path, "e1", "proxy", "money.attempt", {**ext, "kind": "transfer", "payer_id": "acct_chk", "payee_id": "acct_mule",
                                                             "amount_cents": amt, "status": "accepted", "tx_id": f"txn_{3 + i}"})
        db.add_event(path, "e1", "nessie", "transfer.created", {"tx_id": f"txn_{3 + i}", "payer_id": "acct_chk",
                                                                "payee_id": "acct_mule", "amount_cents": amt})

    v = outcome.decide(path, "e1")
    assert v["verdict"] == "scam" and v["grade"] == "confirmed"
    assert any(f["kind"] == "third_party_login" for f in v["evidence"])

    pb = playbook.analyse(db.list_events(path, "e1"), 500000)
    assert pb["third_party"] and pb["subject"] == "s_bad"
    m = pb["metrics"]
    assert m["recon_reads"] == 2 and m["internal_sweeps"] == 1 and m["external_transfers"] == 2
    assert m["declined_attempts"] == 1 and m["structured"] and m["lockout_first"]
    assert pb["profile"]["label"] == "organised account-takeover crew"
    assert pb["fingerprint"]["ops"].startswith("LRCS") and "D" in pb["fingerprint"]["ops"]
    assert pb["fingerprint"]["ua_family"] == "chrome"
    stages = {st["key"]: st for st in pb["stages"]}
    assert stages["lockout"]["done"] and "drop@evil.test" in stages["lockout"]["lines"][0]


def test_watchlist_screens_customers_but_not_decoys(tmp_path):
    path = _setup(tmp_path)
    _agent_run(path)
    db.add_event(path, "e1", "system", "verdict", outcome.decide(path, "e1"))
    wl = intel.watchlist(path)
    assert "acct_mule" in wl and wl["acct_mule"]["role"] == "mule" and wl["acct_mule"]["engagement_id"] == "e1"
    # An ordinary customer paying the mule is a hit; the decoy draining itself into the mule is not.
    assert intel.screen(path, {"kind": "transfer", "payer_id": "acct_customer", "payee_id": "acct_mule"})
    assert intel.screen(path, {"kind": "transfer", "payer_id": "acct_chk", "payee_id": "acct_mule"}) is None
    # The mule paying its own layer is watched, not blocked; a customer paying the layer is blocked.
    db.add_event(path, "e1", "system", "mule.network", {"mule": "acct_mule", "layers": ["acct_layer1"]})
    assert intel.screen(path, {"kind": "transfer", "payer_id": "acct_mule", "payee_id": "acct_layer1"}) is None
    assert intel.screen(path, {"kind": "transfer", "payer_id": "acct_customer", "payee_id": "acct_layer1"})["role"] == "layer"
    row = intel.record_hit(path, {"id": "txn_9", "payer_id": "acct_customer", "payee_id": "acct_mule", "amount_cents": 125000},
                           wl["acct_mule"], "declined", "decision_hook")
    assert row["action"] == "declined" and "e1" in row["reason"]
    assert db.interdiction_for_tx(path, "txn_9")["engagement_id"] == "e1"
    assert db.has_event(path, "e1", "watchlist.hit", tx_id="txn_9")


def test_second_engagement_paying_known_mule_links_crew(tmp_path):
    path = _setup(tmp_path)
    _agent_run(path)
    db.add_event(path, "e1", "system", "verdict", outcome.decide(path, "e1"))
    db.create_engagement(path, "e2", "email", "other@x.test", "Verify")
    db.add_event(path, "e2", "system", "persona.created", {"persona_id": "p2", "customer_id": "c2", "accounts": ["acct_chk2"]})
    db.add_event(path, "e2", "nessie", "transfer.created", {"tx_id": "txn_7", "payer_id": "acct_chk2",
                                                            "payee_id": "acct_mule", "amount_cents": 150000})
    assert intel.note_known_mule(path, "e2", "acct_mule") == "e1"
    v2 = outcome.decide(path, "e2")
    assert v2["grade"] == "confirmed" and any(f["kind"] == "known_mule" for f in v2["evidence"])
    db.add_event(path, "e2", "system", "verdict", v2)
    rel = intel.related(path, "e2", 500000)
    assert rel["others"] == ["e1"] and "same mule account" in rel["why"]
    assert any(c["size"] == 2 and c["shared_mules"] == ["acct_mule"] for c in intel.crews(path, 500000))
