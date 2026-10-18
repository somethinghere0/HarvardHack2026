"""What the honeypot gives back to the bank.

Every scam engagement ends with money in an account the scammer controls — a mule. This module turns
those into a live **watchlist** that screens the whole bank: Nessie asks us (a decision hook) before
any transfer settles, and a transfer from an ordinary customer to a known mule is declined on the
spot, attributed to the engagement that discovered the mule. It also links engagements into **crews**
(same mule, same address, same playbook), draws the **money flow** past the mule, and runs the two
demo simulations: an ordinary customer paying a mule, and the mule laundering what it received.

All reads are over the stored event timeline plus live Nessie; nothing here is cached.
"""
from __future__ import annotations

import asyncio
import random
import secrets

from . import db, playbook
from .nessie import NessieHTTPError, logged as nessie_logged
from .proxy_client import ProxyClient

_LAYER_NAMES = [("Dmitri", "Volkov"), ("Precious", "Adeyemi"), ("Marisol", "Quintero"), ("Teodor", "Ilić"),
                ("Hana", "Kobayashi"), ("Rafael", "Mendes")]


# --- what we know ----------------------------------------------------------------

def decoy_accounts(path: str) -> set[str]:
    out: set[str] = set()
    for e in db.list_events_of_types(path, ("persona.created",)):
        out.update(e["data"].get("accounts") or [])
    return out


def _scam_engagements(path: str) -> dict[str, dict]:
    """Engagements whose verdict is scam → {eid: {grade, verdict_at}}."""
    out: dict[str, dict] = {}
    for e in db.list_events_of_types(path, ("verdict",)):
        if e["data"].get("verdict") == "scam":
            out[e["engagement_id"]] = {"grade": e["data"].get("grade") or "likely", "at": e["created_at"]}
    for eng in db.list_engagements(path):
        if eng["id"] in out and eng.get("grade"):
            out[eng["id"]]["grade"] = eng["grade"]
    return out


def watchlist(path: str) -> dict[str, dict]:
    """Accounts money should never go to: every scam engagement's mule(s), plus the downstream
    accounts a mule paid (the layer). Keyed by account id."""
    own = decoy_accounts(path)
    scams = _scam_engagements(path)
    wl: dict[str, dict] = {}
    for e in db.list_events_of_types(path, ("transfer.created", "withdrawal.created")):
        eid, d = e["engagement_id"], e["data"]
        if eid not in scams or d.get("payer_id") not in own or not d.get("payee_id") or d["payee_id"] in own:
            continue
        w = wl.setdefault(d["payee_id"], {"account_id": d["payee_id"], "role": "mule", "engagement_id": eid,
                                          "grade": scams[eid]["grade"], "first_seen": e["created_at"],
                                          "received_cents": 0, "engagements": []})
        w["received_cents"] += int(d.get("amount_cents") or 0)
        if eid not in w["engagements"]:
            w["engagements"].append(eid)
        if scams[eid]["grade"] == "confirmed":
            w["grade"] = "confirmed"
    for e in db.list_events_of_types(path, ("mule.network",)):
        d = e["data"]
        for acct in d.get("layers") or []:
            wl.setdefault(acct, {"account_id": acct, "role": "layer", "engagement_id": e["engagement_id"],
                                 "grade": (wl.get(d.get("mule")) or {}).get("grade", "likely"),
                                 "first_seen": e["created_at"], "received_cents": 0,
                                 "engagements": [e["engagement_id"]], "via": d.get("mule")})
    return wl


def note_known_mule(path: str, eid: str, payee_id: str) -> str | None:
    """A decoy's money just went to a payee another engagement already identified as a mule: that
    other engagement's intel confirms this one. Records watchlist.match once per payee."""
    w = watchlist(path).get(payee_id)
    if not w or eid in w["engagements"] and len(w["engagements"]) == 1:
        return None
    other = next((x for x in w["engagements"] if x != eid), None)
    if not other or db.has_event(path, eid, "watchlist.match", payee_id=payee_id):
        return None
    db.add_event(path, eid, "system", "watchlist.match", {"payee_id": payee_id, "engagement_id": other,
                                                         "first_seen": w["first_seen"]})
    return other


# --- screening (decision hook / poller) ------------------------------------------

def screen(path: str, txn: dict) -> dict | None:
    """Should this pending transfer be stopped? A hit is a transfer INTO a watchlisted account from an
    ordinary customer. Two kinds of payer are let through on purpose: decoys (they are meant to be
    drained — that's how we learn) and watchlisted accounts themselves (a mule paying its layer is the
    laundering we want to map, not freeze; the bank's victims are protected, the network stays
    visible). Returns the watchlist entry on a hit, else None."""
    payee, payer = txn.get("payee_id"), txn.get("payer_id")
    if not payee or (txn.get("kind") or "transfer") != "transfer":
        return None
    if payer in decoy_accounts(path):
        return None
    wl = watchlist(path)
    if payer in wl:
        return None
    return wl.get(payee)


def record_hit(path: str, txn: dict, hit: dict, action: str, source: str) -> dict:
    reason = (f"payee {hit['account_id'][-6:]} is a {hit['role']} account identified by honeypot engagement "
              f"{hit['engagement_id']} ({hit['grade']})")
    row = db.add_interdiction(path, {"tx_id": txn.get("id"), "payer_id": txn.get("payer_id"), "payee_id": txn.get("payee_id"),
                                     "amount_cents": txn.get("amount_cents"), "action": action, "reason": reason,
                                     "engagement_id": hit["engagement_id"], "source": source})
    db.add_event(path, hit["engagement_id"], "system", "watchlist.hit", {
        "tx_id": txn.get("id"), "payer_id": txn.get("payer_id"), "payee_id": txn.get("payee_id"),
        "amount_cents": txn.get("amount_cents"), "action": action, "source": source, "role": hit["role"]})
    return row


# --- crews: which engagements are the same people ---------------------------------

def _profile(path: str, eid: str, limit_cents: int) -> dict:
    events = db.list_events(path, eid)
    pb = playbook.analyse(events, limit_cents)
    own = set()
    for e in events:
        if e["type"] == "persona.created":
            own.update(e["data"].get("accounts") or [])
    mules = {e["data"].get("payee_id") for e in events if e["type"] == "transfer.created"
             and e["data"].get("payer_id") in own and e["data"].get("payee_id") not in own and e["data"].get("payee_id")}
    for e in events:
        if e["type"] == "mule.network":
            mules.update(e["data"].get("layers") or [])
    ips = {s_["ip"] for s_ in pb["sessions"] if s_["actor"] == "external" and s_.get("ip")}
    fp = pb["fingerprint"]["hash"] if pb.get("fingerprint") and pb.get("third_party") else None
    return {"eid": eid, "mules": mules, "ips": ips, "fingerprint": fp,
            "profile": (pb.get("profile") or {}).get("label"), "subject": pb.get("subject")}


def crews(path: str, limit_cents: int) -> list[dict]:
    scams = _scam_engagements(path)
    profiles = {eid: _profile(path, eid, limit_cents) for eid in scams}
    parent = {eid: eid for eid in profiles}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    ids = list(profiles)
    reasons: dict[tuple, list[str]] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            pa, pb_ = profiles[a], profiles[b]
            why = []
            if pa["mules"] & pb_["mules"]:
                why.append("same mule account")
            if pa["ips"] & pb_["ips"]:
                why.append("same source address")
            if pa["fingerprint"] and pa["fingerprint"] == pb_["fingerprint"]:
                why.append("same playbook fingerprint")
            if why:
                union(a, b)
                reasons[(a, b)] = why
    groups: dict[str, list[str]] = {}
    for eid in ids:
        groups.setdefault(find(eid), []).append(eid)
    out = []
    for root, members in groups.items():
        members.sort(key=lambda e: scams[e]["at"])
        shared_mules = set.intersection(*(profiles[m]["mules"] for m in members)) if len(members) > 1 else set()
        links = [{"a": a, "b": b, "why": w} for (a, b), w in reasons.items() if a in members and b in members]
        out.append({"id": "crew_" + root[:6], "engagements": members, "size": len(members),
                    "mules": sorted(set().union(*(profiles[m]["mules"] for m in members))),
                    "shared_mules": sorted(shared_mules),
                    "ips": sorted(set().union(*(profiles[m]["ips"] for m in members))),
                    "profiles": sorted({profiles[m]["profile"] for m in members if profiles[m]["profile"]}),
                    "links": links, "first_seen": scams[members[0]]["at"], "last_seen": scams[members[-1]]["at"]})
    out.sort(key=lambda g: (-g["size"], g["last_seen"]), reverse=False)
    return out


def related(path: str, eid: str, limit_cents: int) -> dict:
    for g in crews(path, limit_cents):
        if eid in g["engagements"]:
            others = [m for m in g["engagements"] if m != eid]
            why = sorted({w for l in g["links"] if eid in (l["a"], l["b"]) for w in l["why"]})
            return {"crew": g["id"], "others": others, "why": why, "size": g["size"]}
    return {"crew": None, "others": [], "why": [], "size": 1}


# --- money flow: follow it past the mule --------------------------------------

async def flow(s, eid: str, depth: int = 2) -> dict:
    """Nodes and edges from the decoy's accounts outward: decoy → mule → layer → cash. Everything
    past the decoy is read live from Nessie, which is the whole point: in this sandbox the bank sees
    the entire network, the way a consortium view would."""
    events = db.list_events(s.db_path, eid)
    created = next((e["data"] for e in events if e["type"] == "persona.created"), {})
    own = list(created.get("accounts") or [])
    types = created.get("account_types") or {}
    by_tx = {e["data"].get("tx_id"): e["data"] for e in events if e["type"] == "money.attempt" and e["data"].get("tx_id")}
    nessie = nessie_logged(s, eid)
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_tx: set[str] = set()

    def node(acct: str, role: str, **extra):
        n = nodes.setdefault(acct, {"id": acct, "role": role, "label": acct[-6:], **extra})
        if role == "decoy":
            n["role"] = "decoy"
        return n

    async def read(acct: str, role: str, level: int):
        try:
            a, txs = await asyncio.gather(nessie.get_account(acct), nessie.list_transactions(acct))
        except Exception as ex:
            node(acct, role, error=str(ex)[:120])
            return
        n = node(acct, role, type=a.get("type"), nickname=a.get("nickname"),
                 balance_cents=a.get("balance_cents"), available_cents=a.get("available_cents"))
        if role == "decoy":
            n["type"] = types.get(acct) or a.get("type")
        for t in txs:
            tid = t.get("id") or t.get("_id")
            if t.get("payer_id") != acct or tid in seen_tx:
                continue
            kind = (t.get("kind") or "").lower()
            if kind not in ("transfer", "withdrawal", "purchase"):
                continue
            seen_tx.add(tid)
            to = t.get("payee_id") if kind == "transfer" else f"cash:{acct}"
            who = by_tx.get(tid)
            edges.append({"id": tid, "from": acct, "to": to, "kind": kind, "amount_cents": t.get("amount_cents"),
                          "status": t.get("status"), "at": t.get("created_at"), "description": t.get("description", ""),
                          "by": (who or {}).get("actor"), "sid": (who or {}).get("sid"),
                          "decision_reason": t.get("decision_reason")})
            if kind != "transfer":
                node(to, "cash", label="cash out")
            elif to and to not in nodes and level < depth:
                await read(to, "mule" if role == "decoy" else "layer", level + 1)
            elif to:
                node(to, "mule" if role == "decoy" else "layer")

    try:
        for acct in own:
            await read(acct, "decoy", 0)
    finally:
        await nessie.aclose()
    wl = watchlist(s.db_path)
    for n in nodes.values():
        if n["id"] in wl:
            n["watchlisted"] = True
            n["grade"] = wl[n["id"]]["grade"]
    return {"nodes": list(nodes.values()), "edges": edges, "decoy_accounts": own}


# --- demo simulations --------------------------------------------------------------

def mules_of(path: str, eid: str) -> list[str]:
    events = db.list_events(path, eid)
    own = set()
    for e in events:
        if e["type"] == "persona.created":
            own.update(e["data"].get("accounts") or [])
    seen, out = set(), []
    for e in events:
        d = e["data"]
        if e["type"] == "transfer.created" and d.get("payer_id") in own and d.get("payee_id") and d["payee_id"] not in own \
                and d["payee_id"] not in seen:
            seen.add(d["payee_id"])
            out.append(d["payee_id"])
    return out


async def _settle_quietly(nessie, tx_id: str | None) -> None:
    """Post a transaction now. Our own decision hook owns pending transfers, so approve out of band
    first (otherwise settle waits for Nessie's sweep to ask the hook), then fast-forward the window."""
    if not tx_id:
        return
    for call in (lambda: nessie.decide_transaction(tx_id, "approve"), lambda: nessie.settle_transaction(tx_id)):
        try:
            await call()
        except Exception:
            pass


async def launder(s, eid: str, limit_cents: int) -> dict:
    """Play the scammer's next move, in the open: the mule fans what it received out to a fresh layer
    of accounts in chunks under the transfer limit, keeps almost nothing, and one layer account
    cashes out. Simulated downstream behaviour from known typologies — labelled as such in the UI —
    but every hop is a real Nessie transaction, so the bank's own feed sees the whole network."""
    mules = mules_of(s.db_path, eid)
    if not mules:
        raise ValueError("this engagement has no mule yet (nothing left the decoy)")
    mule = mules[0]
    nessie = nessie_logged(s, eid)
    try:
        # The drain may still be in its pending window; post it so the mule can spend it.
        for e in db.list_events(s.db_path, eid):
            if e["type"] == "transfer.created" and e["data"].get("payee_id") == mule:
                await _settle_quietly(nessie, e["data"].get("tx_id"))
        available = 0
        for _ in range(10):
            a = await nessie.get_account(mule)
            available = int(a.get("available_cents") or 0)
            if available > 0:
                break
            await asyncio.sleep(2)
        if available < 3000:
            raise ValueError(f"mule {mule[-6:]} has only ${available / 100:,.2f} available")
        first, last = random.choice(_LAYER_NAMES)
        cust = await nessie.create_customer({"first_name": first, "last_name": last,
                                             "address": {"street_number": str(random.randint(10, 9999)), "street_name": "Industrial Pkwy",
                                                         "city": "Doral", "state": "FL", "zip": "33166"}})
        cid = cust.get("id") or cust.get("_id")
        layers = []
        for i in range(3):
            acc = await nessie.create_account(cid, {"type": "Checking", "nickname": f"Operating {i + 1}", "balance_cents": 0})
            layers.append(acc.get("id") or acc.get("_id"))
        # Keep a token amount in the mule (a pass-through account never zeroes exactly), split the
        # rest unevenly and under the limit, never a round number.
        keep = random.randint(1100, 4900)
        pot = available - keep
        cap = max(1000, (limit_cents or 500000) - random.randint(2000, 9000))
        shares = [0.41, 0.34, 0.25]
        hops = []
        for acct, share in zip(layers, shares):
            amt = min(int(pot * share) - random.randint(1, 99), cap)
            if amt <= 0:
                continue
            try:
                tx = await nessie.transfer(mule, acct, amt, "Invoice settlement")
            except NessieHTTPError as ex:
                hops.append({"to": acct, "amount_cents": amt, "error": str(ex.detail)[:120]})
                continue
            hops.append({"to": acct, "amount_cents": amt, "tx_id": tx.get("id")})
            await _settle_quietly(nessie, tx.get("id"))
        result = {"mule": mule, "layer_customer": cid, "layers": layers, "hops": hops, "cashout": None,
                  "kept_cents": keep, "simulated": True}
        # The layer is on the watchlist from this moment; the cash-out follows once a hop has posted.
        db.add_event(s.db_path, eid, "system", "mule.network", result)
        cash = None
        good = [h for h in hops if h.get("tx_id")]
        if good:
            target = good[0]
            amt = int(target["amount_cents"] * 0.6) - random.randint(1, 99)
            for _ in range(45):  # the hosted API posts within about a minute of the window closing
                a = await nessie.get_account(target["to"])
                if int(a.get("available_cents") or 0) >= amt:
                    break
                await asyncio.sleep(2)
            try:
                w = await nessie.withdraw(target["to"], amt, "ATM withdrawal")
                cash = {"account": target["to"], "amount_cents": amt, "tx_id": w.get("id")}
                await _settle_quietly(nessie, w.get("id"))
            except NessieHTTPError as ex:
                cash = {"account": target["to"], "amount_cents": amt, "error": str(ex.detail)[:120]}
            db.add_event(s.db_path, eid, "system", "mule.cashout", {"mule": mule, **cash})
        return {**result, "cashout": cash}
    finally:
        await nessie.aclose()


async def customer_pays_mule(s, mule: str | None, amount_cents: int, internal_secret: str) -> dict:
    """An ordinary Bank of USA customer — not a decoy — tries to send money to a watchlisted account,
    the way the next victim of the same scam would. Returns what the bank did about it."""
    wl = watchlist(s.db_path)
    if not mule:
        ranked = sorted(wl.values(), key=lambda w: (w["grade"] == "confirmed", w["first_seen"]), reverse=True)
        mule = ranked[0]["account_id"] if ranked else None
    if not mule:
        raise ValueError("the watchlist is empty — run a scam through first")
    proxy = ProxyClient(s.proxy_url)
    first, last = random.choice([("Grace", "Okafor"), ("Liam", "Petrov"), ("Noor", "Haddad"), ("Evan", "Castillo")])
    res = await proxy.signup({"username": f"customer_{secrets.token_hex(3)}", "password": secrets.token_urlsafe(12),
                              "first_name": first, "last_name": last,
                              "address": {"street_number": str(random.randint(10, 999)), "street_name": "Maple Ave",
                                          "city": "Arlington", "state": "VA", "zip": "22201"}})
    token, cid = res["token"], res["customer_id"]
    acct = await proxy.open_account(token, cid, {"type": "Checking", "nickname": "Checking", "balance_cents": 0})
    acct_id = acct.get("id") or acct.get("_id")
    nessie = nessie_logged(s, "watchlist")
    try:
        dep = await proxy.deposit(token, acct_id, amount_cents + 150000, "Payroll — direct deposit")
        await _settle_quietly(nessie, dep.get("id") or dep.get("_id"))
        for _ in range(15):
            a = await nessie.get_account(acct_id)
            if int(a.get("available_cents") or 0) >= amount_cents:
                break
            await asyncio.sleep(2)
        try:
            tx = await proxy.transfer(token, acct_id, mule, amount_cents, "Protected holding account")
        except Exception as ex:
            return {"customer": {"name": f"{first} {last}", "account": acct_id}, "mule": mule,
                    "amount_cents": amount_cents, "status": "rejected", "error": str(ex)[:200]}
        tx_id = tx.get("id") or tx.get("_id")
        final, row = None, None
        for _ in range(16):  # the feed screens it within seconds; the hook's own call may come later
            try:
                final = await nessie.get_transaction(tx_id)
            except Exception:
                final = None
            row = db.interdiction_for_tx(s.db_path, tx_id)
            if (final and final.get("status") not in (None, "pending")) or row:
                break
            await asyncio.sleep(1.5)
        return {"customer": {"name": f"{first} {last}", "account": acct_id}, "mule": mule, "amount_cents": amount_cents,
                "tx_id": tx_id, "status": (final or {}).get("status", "pending"),
                "decision_reason": (final or {}).get("decision_reason"), "interdiction": row,
                "watchlist_entry": wl.get(mule)}
    finally:
        await nessie.aclose()
