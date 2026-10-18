"""Runs INSIDE a Daytona sandbox, one per customer "case". The orchestrator hands it that customer's
transactions (Nessie generated them, with some fraud planted and nothing labelled); the sandbox scores
each transaction with behavioural rules and escalates only the borderline ones to Claude. It reports
back which transactions it flagged — the orchestrator compares that to the truth to score the run.

Why a sandbox per case: each runs untrusted, bank-shaped data in isolation, and hundreds run at once.
Claude is NOT called on every transaction — only the few a rules pass can't settle — so a 1000-sandbox
swarm stays cheap and fast.

Input:  CASE_JSON env (or /tmp/case.json) = {"case_id", "scenario", "transactions":[...], "accounts":[...]}
Output: a JSON line on stdout, and (if ORCHESTRATOR_URL is set) POSTed to /internal/case-result.
Env: ORCHESTRATOR_URL, INTERNAL_SECRET, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, CLAUDE_BUDGET (max escalations)."""
from __future__ import annotations

import json
import os
import statistics
import time
from collections import defaultdict

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
CLAUDE_BUDGET = int(os.environ.get("CLAUDE_BUDGET", "6"))

# A transaction scores points for each suspicious signal. >= FLAG posts a flag outright; the grey band
# [REVIEW, FLAG) is what we hand to Claude — the cases rules alone can't settle.
FLAG, REVIEW = 70, 38


def load_case() -> dict:
    raw = os.environ.get("CASE_JSON")
    if raw:
        return json.loads(raw)
    with open(os.environ.get("CASE_FILE", "/tmp/case.json")) as f:
        return json.load(f)


def amount(t: dict) -> int:
    return abs(int(t.get("amount_cents") or 0))


def score_txn(t: dict, ctx: dict) -> tuple[int, list[str]]:
    """Behavioural score for one transaction, from the account's own history (ctx). Returns
    (points, reasons). No transaction is 'fraud' on its own — it's fraud relative to the customer."""
    pts, why = 0, []
    amt = amount(t)
    kind = (t.get("kind") or "").lower()
    desc = (t.get("description") or "").upper()
    status = (t.get("status") or "").lower()

    # Velocity: this charge sits in a burst of activity in a short window.
    if ctx["burst"]:
        pts += 35
        why.append("burst of activity")
    # Amount well above this account's normal spend, or in its top slice.
    if ctx["mean"] and amt > ctx["mean"] * 3 and amt > 30000:
        pts += 30
        why.append("far above usual amount")
    if ctx.get("p90") and amt >= ctx["p90"] and amt > 30000:
        pts += 15
        why.append("top-decile amount")
    # Card-testing shape: a tiny charge, or a declined/cancelled attempt.
    if amt and amt < 300:
        pts += 25
        why.append("tiny amount (card testing)")
    if status in ("declined", "cancelled"):
        pts += 30
        why.append(f"{status} attempt")
    # Structuring: amount just under a round $ threshold.
    for thresh in (100000, 500000, 1000000):
        if 0 < thresh - amt <= 5000:
            pts += 35
            why.append("just under a reporting threshold")
            break
    # Money leaving to a brand-new EXTERNAL counterparty (not one of the customer's own accounts).
    payee = t.get("payee_id")
    if kind == "transfer" and payee and payee not in ctx.get("own_accounts", set()):
        if payee in ctx["new_payees"]:
            pts += 45
            why.append("transfer to a new external payee")
        elif amt > 100000:
            pts += 40
            why.append("large external transfer")
        else:
            pts += 20
            why.append("external transfer")
    # Out-of-network / foreign ATM cash-out.
    if "ATM" in desc and ("OUT-OF-NETWORK" in desc or "FOREIGN" in desc or "INTL" in desc):
        pts += 30
        why.append("out-of-network ATM")
    # Category the customer never spends in.
    cat = t.get("merchant_category") or t.get("category")
    if cat and ctx["categories"] and cat not in ctx["categories"]:
        pts += 20
        why.append("unusual category")
    # A later dispute is strong evidence the original was fraud.
    if kind in ("chargeback", "refund") and t.get("parent_transaction_id"):
        pts += 15
        why.append("disputed later")
    return pts, why


def build_context(txns: list) -> dict:
    """Per-account baselines the score reads: typical amount, burst windows, first-seen payees,
    and the categories the customer normally shops in."""
    by_acct = defaultdict(list)
    for t in txns:
        acct = t.get("payer_id") or t.get("account_id") or t.get("payee_id")
        by_acct[acct].append(t)
    ctx_for = {}
    for acct, items in by_acct.items():
        items.sort(key=lambda t: t.get("created_at") or "")
        amts = [amount(t) for t in items if amount(t)]
        mean = statistics.mean(amts) if amts else 0
        p90 = sorted(amts)[int(len(amts) * 0.9)] if len(amts) >= 10 else (max(amts) if amts else 0)
        cats = {t.get("merchant_category") or t.get("category") for t in items if (t.get("merchant_category") or t.get("category"))}
        # Payees seen after the first third of history look "new".
        seen, new_payees = set(), set()
        cut = len(items) // 3
        for i, t in enumerate(items):
            pid = t.get("payee_id")
            if pid and i >= cut and pid not in seen:
                new_payees.add(pid)
            if pid:
                seen.add(pid)
        ctx_for[acct] = {"mean": mean, "p90": p90, "categories": cats, "new_payees": new_payees, "items": items}
    # Flag bursts: 4+ transactions within 10 minutes on an account.
    for acct, c in ctx_for.items():
        times = []
        for t in c["items"]:
            try:
                times.append(time.mktime(time.strptime((t.get("created_at") or "")[:19], "%Y-%m-%dT%H:%M:%S")))
            except Exception:
                times.append(0)
        burst_ids = set()
        for i, ti in enumerate(times):
            near = [j for j, tj in enumerate(times) if 0 <= ti - tj < 600 or 0 <= tj - ti < 600]
            if len(near) >= 4:
                burst_ids.update(c["items"][j].get("id") for j in near)
        c["burst_ids"] = burst_ids
    return ctx_for


def claude_review(client, batch: list) -> dict:
    """One call for a batch of borderline transactions. Returns {id: bool flagged}."""
    rows = [{"id": b["id"], "amount": b["amount"], "kind": b["kind"], "desc": b["desc"]} for b in batch]
    prompt = ("You are a bank fraud analyst. Each row is a transaction our rules found borderline. "
              "Decide which are fraudulent given typical consumer banking. Reply ONLY as JSON "
              '{"fraud_ids": ["..."]}.\n' + json.dumps(rows))
    msg = client.messages.create(model=MODEL, max_tokens=400,
                                 messages=[{"role": "user", "content": prompt}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        ids = set(json.loads(txt[txt.find("{"):txt.rfind("}") + 1]).get("fraud_ids", []))
    except Exception:
        ids = set()
    return {t.get("id"): (t.get("id") in ids) for t in batch}


def main() -> None:
    t0 = time.time()
    case = load_case()
    txns = case.get("transactions", [])
    ctx_for = build_context(txns)

    own = set(case.get("own_accounts") or ctx_for.keys())
    flagged, borderline = {}, []
    for t in txns:
        acct = t.get("payer_id") or t.get("account_id") or t.get("payee_id")
        ctx = ctx_for.get(acct, {"mean": 0, "categories": set(), "new_payees": set()})
        ctx = {**ctx, "burst": t.get("id") in ctx.get("burst_ids", set()), "own_accounts": own}
        pts, why = score_txn(t, ctx)
        if pts >= FLAG:
            flagged[t.get("id")] = {"by": "rules", "score": pts, "why": why}
        elif pts >= REVIEW:
            borderline.append({"id": t.get("id"), "score": pts, "why": why,
                               "amount": amount(t) / 100, "kind": t.get("kind"),
                               "desc": (t.get("description") or "")[:70]})

    used_claude = 0
    if borderline and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            for i in range(0, min(len(borderline), CLAUDE_BUDGET * 10), 10):
                batch = borderline[i:i + 10]
                verdicts = claude_review(client, batch)
                used_claude += 1
                for b in batch:
                    if verdicts.get(b["id"]):
                        flagged[b["id"]] = {"by": "claude", "why": ["claude: fraudulent"]}
                if used_claude >= CLAUDE_BUDGET:
                    break
        except Exception as e:
            print("claude review failed:", e)

    # Nessie never labels individual transactions (finding the fraud is the whole exercise), so a
    # sandbox can't know per-row truth. It reports what it flagged; the orchestrator compares that to
    # the planted count Nessie reports for this scenario.
    by_rules = sum(1 for v in flagged.values() if v["by"] == "rules")
    by_claude = sum(1 for v in flagged.values() if v["by"] == "claude")
    result = {
        "case_id": case.get("case_id"), "scenario": case.get("scenario"),
        "n_txns": len(txns), "flagged": len(flagged),
        "flagged_rules": by_rules, "flagged_claude": by_claude,
        "used_claude": used_claude, "ms": int((time.time() - t0) * 1000),
        "host": os.environ.get("HOSTNAME", ""),
        "borderline": len(borderline),
        "borderline_txns": borderline[:40],   # the orchestrator may escalate these to Claude
        "samples": [{"id": k, **v} for k, v in list(flagged.items())[:12]],
    }
    print(json.dumps(result))

    orch, secret = os.environ.get("ORCHESTRATOR_URL"), os.environ.get("INTERNAL_SECRET")
    if orch and secret:
        try:
            import httpx
            httpx.post(f"{orch.rstrip('/')}/internal/case-result", json=result,
                       headers={"X-Internal-Secret": secret}, timeout=15)
        except Exception as e:
            print("report failed:", e)


if __name__ == "__main__":
    main()
