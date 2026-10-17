"""Runs INSIDE the Daytona sandbox (uploaded as a file); must not import anything from `app`.

Usage: python runner.py job.json   ->   prints one line `REPORT:<json>` on stdout.
It opens each URL in headless Chromium, fills any forms with the decoy persona, submits, and records what the page
does. It never downloads files, never answers dialogs, and only ever types decoy data.
"""
import base64
import json
import re
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

# Order matters: first match wins.
KINDS = [
    ("cvv", r"cvv|cvc|security.?code|card.?code"),
    ("card", r"card.?(number|no)|cc.?num|ccnum|credit.?card|cardnumber"),
    ("expiry", r"expir|exp.?date|valid.?thru|mm.?/.?yy"),
    ("ssn", r"\bssn\b|social.?security"),
    ("routing", r"routing|aba|sort.?code"),
    ("account", r"account.?(number|no|num)|\bacct\b|\biban\b"),
    ("pin", r"\bpin\b|passcode"),
    ("otp", r"otp|one.?time|verification.?code|2fa|sms.?code|auth(entication)?.?code"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|tel\b"),
    ("zip", r"zip|postal"),
    ("first_name", r"first.?name|given.?name|fname"),
    ("last_name", r"last.?name|sur.?name|family.?name|lname"),
    ("username", r"user.?(name|id)|login|customer.?id"),
    ("name", r"full.?name|card.?holder|name"),
    ("address", r"address|street"),
    ("city", r"\bcity\b"),
]
MAX_STEPS = 3
NAV_TIMEOUT_MS = 20000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")

COLLECT_JS = """() => [...document.querySelectorAll('input, select, textarea')].map((el, i) => {
  const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
  const label = (el.labels && el.labels[0] ? el.labels[0].innerText : '');
  return {i, tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(),
          hint: [el.name, el.id, el.placeholder, el.autocomplete, el.getAttribute('aria-label'), label].join(' '),
          visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'};
})"""


def classify(f):
    if f["type"] == "password":
        return "password"
    hint = f["hint"].lower()
    for kind, pat in KINDS:
        if re.search(pat, hint):
            return kind
    return "email" if f["type"] == "email" else ("phone" if f["type"] == "tel" else None)


def run_url(browser, url, persona):
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, accept_downloads=False,
                              java_script_enabled=True, locale="en-US")
    page = ctx.new_page()
    out = {"url": url, "final_url": url, "title": "", "error": None, "redirects": [], "steps": [],
           "requests": [], "screenshot": None}
    page.on("dialog", lambda d: d.dismiss())
    page.on("download", lambda d: d.cancel())
    page.on("popup", lambda p: p.close())

    def on_request(req):
        if len(out["requests"]) < 200:
            out["requests"].append({"method": req.method, "url": req.url[:500],
                                    "post": (req.post_data or "")[:500] if req.method != "GET" else None})
        if req.redirected_from:
            out["redirects"].append(req.url[:500])

    page.on("request", on_request)
    try:
        page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        for _ in range(MAX_STEPS):
            fields = page.evaluate(COLLECT_JS)
            targets = [(f, classify(f)) for f in fields if f["visible"] and f["type"] not in ("hidden", "submit", "button", "checkbox", "radio")]
            targets = [(f, k) for f, k in targets if k]
            step = {"url": page.url, "fields": sorted({k for _, k in targets}), "submitted": False}
            out["steps"].append(step)
            if not targets:
                break
            els = page.locator("input, select, textarea")
            for f, kind in targets:
                value = persona.get(kind) or persona.get("name", "")
                try:
                    if f["tag"] == "select":
                        els.nth(f["i"]).select_option(index=1, timeout=1500)
                    else:
                        els.nth(f["i"]).fill(str(value), timeout=1500)
                except Exception:
                    pass
            before = page.url
            try:
                btn = page.locator("button[type=submit], input[type=submit], button:not([type])").first
                if btn.count():
                    btn.click(timeout=3000)
                else:
                    page.keyboard.press("Enter")
                step["submitted"] = True
                page.wait_for_load_state("domcontentloaded", timeout=8000)
                page.wait_for_timeout(1500)
            except Exception:
                pass
            if page.url == before and not step["submitted"]:
                break
        out["final_url"] = page.url
        out["title"] = page.title()[:200]
        shot = page.screenshot(type="jpeg", quality=40, full_page=False)
        if len(shot) < 400_000:
            out["screenshot"] = base64.b64encode(shot).decode()
    except Exception as e:  # navigation failure, timeout, crash
        out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    finally:
        ctx.close()
    return out


def main():
    job = json.load(open(sys.argv[1]))
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        for url in job["urls"]:
            results.append(run_url(browser, url, job["persona"]))
        browser.close()
    print("REPORT:" + json.dumps({"results": results}))


if __name__ == "__main__":
    main()
