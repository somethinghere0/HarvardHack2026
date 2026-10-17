from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from email import policy
from html.parser import HTMLParser
from urllib.parse import urlparse

_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_URGENCY = re.compile(r"\b(urgent|immediately|suspended|verify your|confirm your|unusual activity|"
                      r"account (?:has been )?(?:locked|limited)|within 24 hours)\b", re.I)
_SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "cutt.ly", "rb.gy"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v and v.startswith(("http://", "https://")):
                    self.hrefs.append(v)


@dataclass
class Triage:
    sender: str
    subject: str
    urls: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Nothing to detonate and nothing suspicious: safe to release without a sandbox."""
        return not self.urls and not self.flags


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _trusted(domain: str, trusted: tuple[str, ...]) -> bool:
    return any(domain == t or domain.endswith("." + t) for t in trusted)


def triage(raw: bytes, trusted_domains: tuple[str, ...] = ()) -> Triage:
    msg = email.message_from_bytes(raw, policy=policy.default)
    t = Triage(sender=str(msg.get("From", "")), subject=str(msg.get("Subject", "")))
    text = ""
    urls: list[str] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_content()
        except Exception:
            continue
        if ctype == "text/html":
            p = _Links()
            p.feed(body)
            urls += p.hrefs
        else:
            text += body + "\n"
            urls += _URL.findall(body)
    seen: dict[str, None] = {}
    for u in urls:
        if not _trusted(_domain(u), trusted_domains):
            seen[u.rstrip(".,;")] = None
    t.urls = list(seen)

    auth = str(msg.get("Authentication-Results", "")).lower()
    for mech in ("spf", "dkim", "dmarc"):
        if re.search(rf"{mech}=(fail|softfail|none)", auth):
            t.flags.append(f"{mech} did not pass")
    from_dom = re.search(r"@([\w.-]+)", t.sender)
    reply_dom = re.search(r"@([\w.-]+)", str(msg.get("Reply-To", "")))
    if from_dom and reply_dom and from_dom.group(1).lower() != reply_dom.group(1).lower():
        t.flags.append("Reply-To domain differs from sender")
    if _URGENCY.search(t.subject + " " + text):
        t.flags.append("urgent or credential-seeking language")
    if any(_domain(u) in _SHORTENERS for u in t.urls):
        t.flags.append("link shortener")
    if any(re.fullmatch(r"[\d.]+", _domain(u)) for u in t.urls):
        t.flags.append("link to a raw IP address")
    return t
