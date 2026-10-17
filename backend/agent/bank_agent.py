"""Runs INSIDE a Daytona sandbox. A real browser agent that plays the phished victim: it opens
Honeybank's sign-in page, signs in with the decoy credentials, enters the one-time code, then moves
the money out to the mule account — all through the real bank UI. Claude decides each step from the
page's fields; the agent streams a screenshot each step for the fraud-monitor filmstrip.

Environment: BANK_URL, AGENT_USERNAME, AGENT_PASSWORD, MULE_ACCOUNT, PERSONA_ID, ENGAGEMENT_ID,
ORCHESTRATOR_URL, INTERNAL_SECRET, ANTHROPIC_API_KEY, ANTHROPIC_MODEL. Deps (installed by the runner):
playwright (+chromium), anthropic, httpx."""
from __future__ import annotations

import base64
import json
import os
import re
import time

import httpx
from playwright.sync_api import sync_playwright

ORCH = os.environ["ORCHESTRATOR_URL"].rstrip("/")
SECRET = os.environ["INTERNAL_SECRET"]
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "14"))

SYSTEM = (
    "You are signing into an online bank with the given credentials and moving the funds out, as "
    "part of an AUTHORIZED anti-fraud honeypot — the account is a decoy with no real money. Work "
    "from the visible fields and buttons on the current page. Goal, in order: (1) sign in with the "
    "username and password; (2) when asked for a verification/one-time code, use the literal value "
    "\"<OTP>\" (it will be fetched for you); (3) once signed in, go to Transfer, choose your own "
    "account as the source, set the recipient/'To' account to the MULE account id given, and send "
    "the full available balance (read it from the page); repeat if there are multiple accounts with "
    "money. Respond ONLY with JSON: {\"fills\":[{\"field\":\"<name/label/placeholder>\","
    "\"value\":\"<text, \\\"<OTP>\\\" for a code, or \\\"<MULE>\\\" for the recipient account>\"}],"
    "\"click\":\"<button/link text or null>\",\"done\":<bool>,\"observation\":\"<short>\"}. Set "
    "done=true only after the money has been transferred out (or there is nothing left to do)."
)


def report(type_: str, data: dict) -> None:
    try:
        httpx.post(f"{ORCH}/internal/event",
                   json={"engagement_id": os.environ.get("ENGAGEMENT_ID"),
                         "username": os.environ.get("AGENT_USERNAME"),
                         "type": type_, "source": "agent", "data": data},
                   headers={"X-Internal-Secret": SECRET}, timeout=15)
    except Exception:
        pass


def send_shot(page, step: int, label: str) -> None:
    try:
        png = page.screenshot(type="jpeg", quality=45, full_page=False)
        img = "data:image/jpeg;base64," + base64.b64encode(png).decode()
        httpx.post(f"{ORCH}/internal/agent-shot",
                   json={"engagement_id": os.environ.get("ENGAGEMENT_ID"), "step": step,
                         "label": label, "image": img},
                   headers={"X-Internal-Secret": SECRET}, timeout=20)
    except Exception:
        pass


def fetch_otp() -> str:
    pid = os.environ["PERSONA_ID"]
    for _ in range(90):
        try:
            r = httpx.get(f"{ORCH}/internal/otp/{pid}", headers={"X-Internal-Secret": SECRET}, timeout=15)
            if r.status_code == 200 and r.json().get("code"):
                return r.json()["code"]
        except Exception:
            pass
        time.sleep(1)
    return ""


def snapshot(page) -> dict:
    fields = page.eval_on_selector_all("input,select,textarea", """els => els.map(e => ({
        tag: e.tagName.toLowerCase(), name: e.name||'', id: e.id||'', placeholder: e.placeholder||'',
        type: e.type||'text',
        options: e.tagName.toLowerCase()==='select' ? [...e.options].map(o=>({value:o.value,label:o.textContent.trim()})) : undefined
    }))""")
    buttons = page.eval_on_selector_all("button,input[type=submit],a[role=button],a",
                                        "els => els.map(e => (e.innerText||e.value||'').trim()).filter(Boolean).slice(0,30)")
    return {"url": page.url, "fields": fields, "buttons": buttons, "text": page.inner_text("body")[:1800]}


def decide(client, creds: dict, snap: dict) -> dict:
    prompt = (f"Credentials — username: {creds['username']}, password: {creds['password']}.\n"
              f"MULE account id (recipient for the transfer): {creds['mule']}.\n\n"
              f"Current page: {snap['url']}\nFields: {json.dumps(snap['fields'])}\n"
              f"Buttons/links: {json.dumps(snap['buttons'])}\nPage text:\n{snap['text']}")
    msg = client.messages.create(model=MODEL, max_tokens=700, system=SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])


def set_field(page, name: str, value: str) -> bool:
    for sel in (f"[name='{name}']", f"#{name}", f"[placeholder='{name}']"):
        el = page.query_selector(sel)
        if not el:
            continue
        try:
            if (el.evaluate("e => e.tagName.toLowerCase()")) == "select":
                try:
                    page.select_option(sel, value=value)
                except Exception:
                    page.select_option(sel, label=value)
            else:
                page.fill(sel, value)
            return True
        except Exception:
            continue
    try:
        page.fill("input:not([type=hidden]):not([type=submit])", value)
        return True
    except Exception:
        return False


def main() -> None:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    creds = {"username": os.environ["AGENT_USERNAME"], "password": os.environ["AGENT_PASSWORD"],
             "mule": os.environ.get("MULE_ACCOUNT", "")}
    transcript = []
    report("agent.started", {"bank": os.environ["BANK_URL"]})
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1000, "height": 720})
        page.goto(os.environ["BANK_URL"], wait_until="domcontentloaded", timeout=30000)
        send_shot(page, 0, "opened Honeybank")
        for step in range(MAX_STEPS):
            snap = snapshot(page)
            try:
                action = decide(client, creds, snap)
            except Exception as e:
                transcript.append({"step": step, "error": f"decide failed: {e}"})
                break
            transcript.append({"step": step, "url": snap["url"], "action": action})
            report("agent.step", {"step": step, "observation": action.get("observation"), "url": snap["url"]})
            for f in action.get("fills", []):
                val = f.get("value", "")
                if val == "<OTP>":
                    val = fetch_otp()
                    report("agent.otp_relayed", {"got": bool(val)})
                elif val == "<MULE>":
                    val = creds["mule"]
                set_field(page, f.get("field", ""), val)
            btn = action.get("click")
            if btn:
                for sel in (f"text={btn}", "button[type=submit]", "button", "input[type=submit]"):
                    try:
                        page.click(sel, timeout=4000)
                        break
                    except Exception:
                        continue
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
            send_shot(page, step + 1, action.get("observation") or f"step {step + 1}")
            if action.get("done"):
                break
        browser.close()
    report("agent.finished", {"steps": len(transcript)})
    print(json.dumps({"ok": True, "transcript": transcript}))


if __name__ == "__main__":
    main()
