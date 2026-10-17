"""Unit tests for the fraud-indicator engine — pure function over a synthetic event timeline,
no network or services."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db, indicators  # noqa: E402


def _setup(tmp_path):
    path = str(tmp_path / "orch.db")
    db.init_db(path)
    db.create_engagement(path, "e1", "email", "scammer@x.test", "Verify now")
    db.add_event(path, "e1", "system", "persona.created",
                 {"persona_id": "p1", "customer_id": "c1", "accounts": ["acct_own"]})
    return path


def test_clean_engagement_scores_zero(tmp_path):
    path = _setup(tmp_path)
    r = indicators.compute(path, "e1")
    assert r["risk_score"] == 0 and r["tags"] == []


def test_external_drain_flags_expected_indicators(tmp_path):
    path = _setup(tmp_path)
    db.add_event(path, "e1", "proxy", "session.login", {"ip": "1.2.3.4"})
    # Three sub-threshold transfers (structuring) + one large, all to the mule account.
    for amt in (80000, 85000, 90000, 500000):
        db.add_event(path, "e1", "nessie", "transfer.created",
                     {"payer_id": "acct_own", "payee_id": "mule_acct", "amount_cents": amt})
    db.add_event(path, "e1", "nessie", "account.balance_changed", {"balance_cents": 0})
    r = indicators.compute(path, "e1")
    assert set(r["tags"]) >= {"external_payee", "large_transfer", "structuring", "full_drain", "rapid_drain"}
    assert r["risk_score"] == 100


def test_recompute_sets_status_drained(tmp_path):
    path = _setup(tmp_path)
    db.add_event(path, "e1", "nessie", "account.balance_changed", {"balance_cents": 0})
    indicators.recompute_and_store(path, "e1")
    assert db.get_engagement(path, "e1")["status"] == "drained"
