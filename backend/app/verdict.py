from __future__ import annotations

import re
from urllib.parse import urlparse

from .detonation import Detonation

SENSITIVE = {"card", "cvv", "ssn", "routing", "account", "pin"}
EXFIL_HOSTS = re.compile(
    r"(api\.telegram\.org|discord(app)?\.com/api/webhooks|formspree\.io|web3forms\.com|getform\.io|"
    r"script\.google\.com/macros|ngrok|webhook\.site|requestbin|pipedream)", re.I)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _site(host: str) -> str:
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def analyze(report: dict, triage_flags: list[str] | None = None) -> Detonation:
    """Turn a sandbox report into a verdict. Pure function so the rules are unit-testable."""
    flags = triage_flags or []
    evidence: list[str] = []
    destinations: list[str] = []
    verdicts: list[str] = []
    screenshots: list[str] = []
    for r in report.get("results", []):
        host = _host(r["final_url"])
        if r.get("screenshot"):
            screenshots.append(r["screenshot"])
        if r.get("error") and not r.get("steps"):
            verdicts.append("uncertain")
            evidence.append(f"{r['url']}: could not load ({r['error']})")
            continue
        kinds = {k for s in r["steps"] for k in s["fields"]}
        submitted = any(s["submitted"] for s in r["steps"])
        posts = [q for q in r["requests"] if q["method"] in ("POST", "PUT") and q["post"]]
        for q in posts:
            if q["url"] not in destinations:
                destinations.append(q["url"])
        external = [q for q in posts if _site(_host(q["url"])) != _site(host)]
        exfil = [q for q in posts if EXFIL_HOSTS.search(q["url"])]
        if len(r["redirects"]) >= 3:
            evidence.append(f"{r['url']}: {len(r['redirects'])} redirects")
        v = "safe"
        if kinds & SENSITIVE:
            v = "scam"
            evidence.append(f"{host}: asks for {', '.join(sorted(kinds & SENSITIVE))}")
        elif exfil:
            v = "scam"
            evidence.append(f"{host}: form data sent to {_host(exfil[0]['url'])}")
        elif "password" in kinds:
            v = "scam" if (flags or external) else "uncertain"
            evidence.append(f"{host}: login form" + (" posting to another site" if external else ""))
        elif "otp" in kinds:
            v = "scam" if flags else "uncertain"
            evidence.append(f"{host}: asks for a one-time code")
        elif kinds and submitted and external:
            v = "uncertain"
            evidence.append(f"{host}: form posts to {_host(external[0]['url'])}")
        if v == "scam" and external:
            evidence.append(f"{host}: data posted to a different site ({_host(external[0]['url'])})")
        verdicts.append(v)
    if not verdicts:
        return Detonation("uncertain", ["sandbox returned no results"])
    overall = "scam" if "scam" in verdicts else ("uncertain" if "uncertain" in verdicts else "safe")
    return Detonation(overall, evidence, destinations, screenshots[:1])
