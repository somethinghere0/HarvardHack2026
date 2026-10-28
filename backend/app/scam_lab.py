"""The scam-scenario lab + sandbox swarm.

Nessie is the bank AND the source of the fraud: for each scam type we ask Nessie's traffic simulator
to generate a real bank's worth of transactions with that one anomaly planted (it tells us how many it
injected — the only ground truth, since individual rows are never labelled). We split each simulated
bank by customer into independent "cases", fan every case out to its own Daytona sandbox running the
detector, and score what we flagged against Nessie's planted count per scenario. A clean control run
(no fraud) measures false positives exactly.

Why sandboxes: each runs untrusted, bank-shaped data in isolation, and thousands run at once. The
detector is pure-stdlib rules (fast, no deps) and escalates only borderline transactions to Claude —
done here in the orchestrator, capped per scenario, so a huge swarm stays cheap."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time

from . import db
from .nessie import logged as nessie_logged

SCENARIOS = ["account_takeover", "large_transfer_new_payee", "card_testing", "structuring",
             "velocity_spike", "foreign_atm_cashout", "geo_distant", "unusual_category"]
_DETECTOR = os.path.join(os.path.dirname(__file__), "..", "agent", "detector.py")


async def run_swarm(s, rid: str, scenarios: list[str], customers: int, anomaly_rate: float,
                    max_concurrency: int, use_claude: bool) -> None:
    """Drive one swarm run end to end. Updates swarm_runs/swarm_cases as it goes so the dashboard
    streams live."""
    sem = asyncio.Semaphore(max_concurrency)
    plan = scenarios + ["baseline"]
    scen_planted: dict[str, int] = {}
    workers: list = []

    async def worker(case):
        async with sem:
            await _run_case(s, rid, case, use_claude, scen_planted)
            _rollup(s, rid, scen_planted)

    # Simulate each scenario, then immediately fan its cases out to sandboxes — so the grid fills as
    # soon as a scenario's bank is generated, instead of waiting for every simulation first.
    for scenario in plan:
        try:
            sim = await _simulate(s, rid, scenario, customers, 0.05 if scenario == "baseline" else anomaly_rate)
        except Exception as e:
            db.add_event(s.db_path, None, "swarm", "swarm.sim_error", {"run": rid, "scenario": scenario, "error": str(e)})
            continue
        scen_planted[scenario] = sim["planted"]
        for cust_id, txns, own in sim["cases"]:
            cid = secrets.token_hex(8)
            db.add_case(s.db_path, cid, rid, scenario, cust_id)
            workers.append(asyncio.create_task(worker(
                {"cid": cid, "scenario": scenario, "customer_id": cust_id,
                 "transactions": txns, "own_accounts": own})))
        _rollup(s, rid, scen_planted)

    if workers:
        await asyncio.gather(*workers, return_exceptions=True)
    db.update_swarm(s.db_path, rid, status="finished", totals=_totals(s, rid, scen_planted))


async def _nessie_req(nessie, method: str, path: str, **kw):
    """Nessie rate-limits (120/min, stricter on /simulations). Honour 429 Retry-After and back off,
    so a swarm firing many simulations in a row doesn't drop requests."""
    for attempt in range(12):
        r = await nessie._http.request(method, path, **kw)
        if r.status_code != 429:
            r.raise_for_status()
            return r
        wait = float(r.headers.get("Retry-After", "") or 0) or min(2 ** attempt, 20)
        await asyncio.sleep(wait + secrets.randbelow(1000) / 1000)
    r.raise_for_status()
    return r


async def _simulate(s, rid: str, scenario: str, customers: int, anomaly_rate: float) -> dict:
    """Create a Nessie simulation and read its bank back. Returns planted count and per-customer cases."""
    nessie = nessie_logged(s, rid)
    try:
        body = {"mode": "historical", "customers": customers, "anomaly_rate": anomaly_rate,
                "transactions": max(40 * customers, 120), "seed": secrets.randbelow(10_000_000)}
        if scenario != "baseline":
            body["scenarios"] = [scenario]
        r = await _nessie_req(nessie, "POST", "/simulations", json=body)
        sim = r.json()
        sid = sim["id"]
        for _ in range(60):
            g = await _nessie_req(nessie, "GET", f"/simulations/{sid}")
            d = g.json()
            if d.get("status") in ("finished", "stopped"):
                sim = d
                break
            await asyncio.sleep(1.5)
        planted = sim.get("anomalies", 0)
        account_ids = set(sim.get("account_ids") or [])

        # Pull this run's transactions (filtered to its accounts) and the account→customer map.
        txns = await _sim_transactions(nessie, sid, account_ids)
        owners = await _owners(nessie, sim.get("customer_ids") or [])

        by_customer: dict[str, list] = {}
        own_of: dict[str, set] = {}
        acct_customer = {a: c for c, accts in owners.items() for a in accts}
        for c, accts in owners.items():
            own_of[c] = set(accts)
        for t in txns:
            acct = t.get("payer_id") or t.get("account_id") or t.get("payee_id")
            cust = acct_customer.get(acct)
            if cust:
                by_customer.setdefault(cust, []).append(t)
        cases = [(c, items, list(own_of.get(c, []))) for c, items in by_customer.items() if items]
        return {"planted": planted, "cases": cases}
    finally:
        await nessie.aclose()


async def _sim_transactions(nessie, sid: str, account_ids: set) -> list:
    out, cursor = [], None
    for _ in range(10):
        params = {"limit": 5000}
        if cursor:
            params["cursor"] = cursor
        r = await _nessie_req(nessie, "GET", "/transactions", params=params)
        d = r.json()
        items = d.get("items", d) if isinstance(d, dict) else d
        for t in items:
            if sid in (t.get("id") or "") or (t.get("payer_id") in account_ids or t.get("payee_id") in account_ids):
                out.append(t)
        cursor = d.get("next_cursor") if isinstance(d, dict) else None
        if not cursor or len(items) < 5000:
            break
    return out


async def _owners(nessie, customer_ids: list) -> dict:
    owners = {}
    for c in customer_ids:
        try:
            r = await _nessie_req(nessie, "GET", f"/customers/{c}/accounts")
            d = r.json()
            owners[c] = [a["id"] for a in (d.get("items", d) if isinstance(d, dict) else d)]
        except Exception:
            owners[c] = []
    return owners


async def _run_case(s, rid: str, case: dict, use_claude: bool, scen_planted: dict) -> None:
    cid = case["cid"]
    payload = {"case_id": cid, "scenario": case["scenario"],
               "transactions": case["transactions"], "own_accounts": case["own_accounts"]}
    db.update_case(s.db_path, cid, status="booting", n_txns=len(case["transactions"]))
    try:
        result, runtime, sbx = await asyncio.to_thread(_run_sandbox_detector, s, payload)
    except Exception as e:
        db.update_case(s.db_path, cid, status="error", result={"error": str(e)})
        return
    rules = result.get("flagged", 0)
    claude_added = 0
    if use_claude and result.get("borderline_txns"):
        try:
            claude_added = await _claude_escalate(s, result["borderline_txns"])
        except Exception:
            claude_added = 0
    total_flagged = rules + claude_added
    db.update_case(s.db_path, cid, status="done", runtime=runtime, sandbox_id=sbx,
                   n_txns=result.get("n_txns", 0), flagged=total_flagged,
                   used_claude=1 if claude_added else 0,
                   result={**result, "flagged_total": total_flagged, "claude_added": claude_added})


def _run_sandbox_detector(s, payload: dict):
    """Launch one Daytona sandbox, run the stdlib detector over the case, return its JSON. Falls back
    to a local subprocess if Daytona isn't configured."""
    if not s.daytona_api_key or os.environ.get("SWARM_RUNTIME") == "local":
        return _run_local_detector(payload) + ("local", "local")
    from daytona import Daytona, DaytonaConfig
    cfg = DaytonaConfig(api_key=s.daytona_api_key, api_url=s.daytona_api_url or None,
                        target=s.daytona_target or None)
    client = Daytona(cfg)
    # Daytona caps concurrent sandboxes (lower tiers ~10 CPUs). When we hit the cap, wait for a slot
    # and retry rather than failing the case — the swarm processes any number of cases, just fewer at
    # a time. A semaphore keeps us near the cap; this backoff absorbs the overshoot.
    sandbox = None
    for attempt in range(40):
        try:
            sandbox = client.create()
            break
        except Exception as e:
            if "limit" in str(e).lower() and attempt < 39:
                time.sleep(2 + attempt * 0.5 + secrets.randbelow(1000) / 1000)
                continue
            raise
    sbx = getattr(sandbox, "id", "")
    try:
        import base64
        with open(os.path.abspath(_DETECTOR), "rb") as f:
            det = base64.b64encode(f.read()).decode()
        case_b64 = base64.b64encode(json.dumps(payload).encode()).decode()
        sandbox.process.exec(
            f"python3 -c \"import base64,pathlib;pathlib.Path('/tmp/detector.py').write_bytes(base64.b64decode('{det}'));"
            f"pathlib.Path('/tmp/case.json').write_bytes(base64.b64decode('{case_b64}'))\"", timeout=60)
        res = sandbox.process.exec("CASE_FILE=/tmp/case.json python3 /tmp/detector.py", timeout=120)
        out = getattr(res, "result", "") or ""
        line = [l for l in out.splitlines() if l.strip().startswith("{")]
        return (json.loads(line[-1]) if line else {"error": "no output", "raw": out[-300:]}), "daytona", sbx
    finally:
        try:
            sandbox.delete()
        except Exception:
            pass


def _run_local_detector(payload: dict):
    import subprocess
    import sys
    env = {**os.environ, "CASE_JSON": json.dumps(payload)}
    env.pop("ANTHROPIC_API_KEY", None)  # rules-only locally; Claude runs in the orchestrator pass
    r = subprocess.run([sys.executable, os.path.abspath(_DETECTOR)], env=env, capture_output=True, text=True, timeout=120)
    line = [l for l in (r.stdout or "").splitlines() if l.strip().startswith("{")]
    return (json.loads(line[-1]) if line else {"error": "no output", "raw": (r.stderr or "")[-300:]},)


async def _claude_escalate(s, borderline: list, cap: int = 10) -> int:
    """Review the few borderline transactions a case couldn't settle. One batched call; returns how
    many Claude judged fraudulent."""
    if not s.anthropic_api_key:
        return 0
    import anthropic
    rows = [{"id": b["id"], "amount": b.get("amount"), "kind": b.get("kind"), "desc": b.get("desc")}
            for b in borderline[:cap]]
    prompt = ("You are a bank fraud analyst. Each row is a transaction our rules found borderline. "
              "Which are fraudulent, given typical consumer banking? Reply ONLY JSON "
              '{"fraud_ids":["..."]}.\n' + json.dumps(rows))
    client = anthropic.Anthropic(api_key=s.anthropic_api_key)
    msg = await asyncio.to_thread(lambda: client.messages.create(
        model=s.anthropic_model, max_tokens=300, messages=[{"role": "user", "content": prompt}]))
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        return len(json.loads(txt[txt.find("{"):txt.rfind("}") + 1]).get("fraud_ids", []))
    except Exception:
        return 0


def _rollup(s, rid: str, scen_planted: dict) -> None:
    db.update_swarm(s.db_path, rid, totals=_totals(s, rid, scen_planted))


def _totals(s, rid: str, scen_planted: dict) -> dict:
    cases = db.list_cases(s.db_path, rid)
    per: dict[str, dict] = {}
    for c in cases:
        p = per.setdefault(c["scenario"], {"cases": 0, "done": 0, "flagged": 0, "txns": 0, "planted": 0})
        p["cases"] += 1
        p["txns"] += c.get("n_txns") or 0
        if c["status"] == "done":
            p["done"] += 1
            p["flagged"] += c.get("flagged") or 0
    for scenario, planted in scen_planted.items():
        per.setdefault(scenario, {"cases": 0, "done": 0, "flagged": 0, "txns": 0})["planted"] = planted
    stats = db.nessie_call_stats(s.db_path, rid)
    live = sum(1 for c in cases if c["status"] in ("booting", "analyzing"))
    done = sum(1 for c in cases if c["status"] == "done")
    return {"per_scenario": per, "cases": len(cases), "done": done, "live": live,
            "flagged": sum(p["flagged"] for p in per.values()),
            "txns": sum(p["txns"] for p in per.values()),
            "nessie_calls": stats["calls"], "nessie_ms": stats["avg_ms"]}
