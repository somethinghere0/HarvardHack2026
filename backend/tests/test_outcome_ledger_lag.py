"""The verdict must wait for the ledger: a transfer the decoy submitted through the bank site is
scam evidence even before Nessie's own transfer event lands (it has trailed the POST by 40s+)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db, outcome  # noqa: E402

OWN = ["acct_chk", "acct_sav"]


def _setup(tmp_path, eid="e1"):
    path = str(tmp_path / "orch.db")
    db.init_db(path)
    db.create_engagement(path, eid, "email", "scammer@x.test", "URGENT")
    db.add_event(path, eid, "system", "persona.created", {"persona_id": "p1", "customer_id": "c1", "accounts": OWN})
    db.add_event(path, eid, "agent", "agent.finished", {"summary": "moved the money", "complied": True})
    return path


def test_submitted_transfer_holds_verdict_until_ledger_confirms(tmp_path):
    path = _setup(tmp_path)
    db.add_event(path, "e1", "proxy", "request", {"method": "POST", "path": "/accounts/acct_chk/transfers", "status": 201})
    db.add_event(path, "e1", "proxy", "money.attempt", {"kind": "transfer", "payer_id": "acct_chk", "payee_id": "acct_mule",
                                                         "amount_cents": 82188, "tx_id": "txn_1", "status": "accepted"})
    pending = outcome.submitted_unconfirmed(db.list_events(path, "e1"))
    assert len(pending) == 1 and pending[0]["via"] == "money.attempt"
    v = outcome.decide(path, "e1")
    assert v["verdict"] == "error"          # held for review, never "safe"
    assert "hasn't confirmed" in v["reason"]

    # The late ledger event lands: now it's a scam, and the hold clears.
    db.add_event(path, "e1", "nessie", "transfer.created", {"tx_id": "txn_1", "payer_id": "acct_chk",
                                                             "payee_id": "acct_mule", "amount_cents": 82188})
    assert outcome.submitted_unconfirmed(db.list_events(path, "e1")) == []
    v = outcome.decide(path, "e1")
    assert v["verdict"] == "scam" and v["vector"] == "payment_fraud"


def test_request_log_alone_counts_as_submission(tmp_path):
    """Older proxies only logged the raw request; a 2xx money POST on a decoy account still counts."""
    path = _setup(tmp_path)
    db.add_event(path, "e1", "proxy", "request", {"method": "POST", "path": "/accounts/acct_chk/transfers", "status": 201})
    assert outcome.decide(path, "e1")["verdict"] == "error"


def test_no_submission_is_safe(tmp_path):
    path = _setup(tmp_path)
    db.add_event(path, "e1", "proxy", "request", {"method": "GET", "path": "/accounts/acct_chk/transactions", "status": 200})
    db.add_event(path, "e1", "proxy", "request", {"method": "POST", "path": "/accounts/acct_other/transfers", "status": 201})
    db.add_event(path, "e1", "proxy", "money.attempt", {"kind": "transfer", "payer_id": "acct_chk", "payee_id": "acct_sav",
                                                         "amount_cents": 100, "tx_id": "txn_int", "status": "accepted"})
    db.add_event(path, "e1", "proxy", "money.attempt", {"kind": "transfer", "payer_id": "acct_chk", "payee_id": "acct_mule",
                                                         "amount_cents": 999999, "tx_id": None, "status": "rejected"})
    assert outcome.submitted_unconfirmed(db.list_events(path, "e1")) == []
    assert outcome.decide(path, "e1")["verdict"] == "safe"
