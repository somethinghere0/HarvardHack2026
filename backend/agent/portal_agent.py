"""Runs INSIDE a Daytona sandbox. A real browser agent: it opens the (scammer's) portal, and uses
Claude to decide what to type — entering the decoy credentials and the one-time code — until the
portal says it's done. It fetches the OTP from the orchestrator (the "victim's inbox") at runtime.

Config comes from environment:
  PORTAL_URL, AGENT_USERNAME, AGENT_PASSWORD, PERSONA_ID, ENGAGEMENT_ID,
  ORCHESTRATOR_URL, INTERNAL_SECRET, ANTHROPIC_API_KEY, ANTHROPIC_MODEL

Dependencies (installed by the runner before this runs): playwright (+chromium), anthropic, httpx.
Prints a single JSON line of the transcript as its result."""
from __future__ import annotations

import json
import os
import time

import httpx
from playwright.sync_api import sync_playwright

ORCH = os.environ["ORCHESTRATOR_URL"].rstrip("/")
SECRET = os.environ["INTERNAL_SECRET"]
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "8"))

SYSTEM = (
    "You are an automated user completing an account-verification flow on a web portal, as part of "
    "an authorized anti-fraud honeypot (the account is a decoy; no real money). You are given the "
    "visible input fields and buttons on the current page. Decide the next actions to sign in and "
    "complete any verification. Respond ONLY with JSON: "
    '{"fills":[{"field":"<name/label/placeholder>","value":"<text or \\"<OTP>\\" for a one-time '
    'code>"}],"click":"<button name/text or null>","done":<bool>,"observation":"<short>"}. '
    "Use the provided username/password for the login fields. Use \"<OTP>\" for any field asking for "
    "a verification/one-time code; it will be fetched for you. Set done=true when the page confirms "
    "success or there is nothing left to do."
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


def fetch_otp() -> str:
    pid = os.environ["PERSONA_ID"]
    for _ in range(60):
        try:
            r = httpx.get(f"{ORCH}/internal/otp/{pid}", headers={"X-Internal-Secret": SECRET}, timeout=15)
            if r.status_code == 200 and r.json().get("code"):
                return r.json()["code"]
        except Exception:
            pass
        time.sleep(1)
    return ""


def snapshot(page) -> dict:
    inputs = page.eval_on_selector_all("input,select,textarea", """els => els.map(e => ({
        name: e.name || '', id: e.id || '', placeholder: e.placeholder || '', type: e.type || 'text'
    }))""")
    buttons = page.eval_on_selector_all("button,input[type=submit],a[role=button]",
                                        "els => els.map(e => (e.innerText||e.value||'').trim()).filter(Boolean)")
    text = page.inner_text("body")[:1500]
    return {"url": page.url, "inputs": inputs, "buttons": buttons, "text": text}


def decide(client, creds: dict, snap: dict) -> dict:
    prompt = (f"Credentials — username: {creds['username']}, password: {creds['password']}.\n\n"
              f"Current page URL: {snap['url']}\nVisible inputs: {json.dumps(snap['inputs'])}\n"
              f"Buttons: {json.dumps(snap['buttons'])}\nPage text:\n{snap['text']}")
    msg = client.messages.create(model=MODEL, max_tokens=600, system=SYSTEM,
                                 messages=[{"role": "user", "content": prompt}])
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    return json.loads(txt[txt.find("{"):txt.rfind("}") + 1])


def fill_field(page, name: str, value: str) -> bool:
    for sel in (f"[name='{name}']", f"#{name}", f"[placeholder='{name}']",
                f"input[type='{name}']"):
        try:
            if page.query_selector(sel):
                page.fill(sel, value)
                return True
        except Exception:
            continue
    # last resort: first empty text/password/email input
    try:
        page.fill("input:not([type=hidden]):not([type=submit])", value)
        return True
    except Exception:
        return False


def main() -> None:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    creds = {"username": os.environ["AGENT_USERNAME"], "password": os.environ["AGENT_PASSWORD"]}
    transcript = []
    report("agent.started", {"portal": os.environ["PORTAL_URL"]})
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.goto(os.environ["PORTAL_URL"], wait_until="domcontentloaded", timeout=30000)
        for step in range(MAX_STEPS):
            snap = snapshot(page)
            try:
                action = decide(client, creds, snap)
            except Exception as e:
                transcript.append({"step": step, "error": f"decide failed: {e}"})
                break
            transcript.append({"step": step, "url": snap["url"], "observation": action.get("observation"),
                               "action": action})
            report("agent.step", {"step": step, "observation": action.get("observation"),
                                  "url": snap["url"]})
            for f in action.get("fills", []):
                val = f.get("value", "")
                if val == "<OTP>":
                    val = fetch_otp()
                    report("agent.otp_relayed", {"got": bool(val)})
                fill_field(page, f.get("field", ""), val)
            btn = action.get("click")
            if btn:
                try:
                    page.click(f"text={btn}", timeout=5000)
                except Exception:
                    try:
                        page.click("button, input[type=submit]", timeout=5000)
                    except Exception:
                        pass
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
            if action.get("done"):
                break
        browser.close()
    report("agent.finished", {"steps": len(transcript)})
    print(json.dumps({"ok": True, "transcript": transcript}))


if __name__ == "__main__":
    main()
