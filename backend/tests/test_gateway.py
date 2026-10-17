import asyncio
import base64
from email.message import EmailMessage

import httpx

from app.config import Settings
from app.detonation import Detonation
from app.gateway import Gateway
from app.gmail import GmailClient
from app.triage import triage


def mail(body="hello", subject="Hi", sender="a@example.com", html=None, **headers) -> bytes:
    m = EmailMessage()
    m["From"], m["Subject"], m["To"] = sender, subject, "me@example.com"
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return m.as_bytes()


def test_plain_mail_is_clean():
    assert triage(mail()).clean


def test_links_and_flags_extracted():
    t = triage(mail("URGENT: verify your account http://bit.ly/x", Authentication_Results="mx; spf=fail"))
    assert t.urls == ["http://bit.ly/x"]
    assert {"spf did not pass", "link shortener", "urgent or credential-seeking language"} <= set(t.flags)


def test_html_href_and_trusted_domain():
    t = triage(mail(html='<a href="https://login.evil.test/a">x</a><a href="https://docs.good.com/z">y</a>'),
               trusted_domains=("good.com",))
    assert t.urls == ["https://login.evil.test/a"]


def test_reply_to_mismatch():
    assert "Reply-To domain differs from sender" in triage(mail(Reply_To="x@other.test")).flags


class FakeDetonator:
    def __init__(self, verdict):
        self.verdict = verdict

    async def detonate(self, urls, flags=None):
        return Detonation(self.verdict, ["fake"])


def make_gateway(raw: bytes, verdict="safe"):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        if p.endswith("/labels") and req.method == "GET":
            return httpx.Response(200, json={"labels": []})
        if p.endswith("/labels"):
            name = req.read().decode()
            return httpx.Response(200, json={"id": "L_" + str(abs(hash(name)) % 999)})
        if p.endswith("/settings/filters"):
            return httpx.Response(200, json={})
        if p.endswith("/modify"):
            calls.append(req.read().decode())
            return httpx.Response(200, json={})
        if "/messages/" in p:
            return httpx.Response(200, json={"raw": base64.urlsafe_b64encode(raw).decode()})
        return httpx.Response(200, json={"messages": [{"id": "m1"}]})

    gmail = GmailClient("id", "secret", "refresh", transport=httpx.MockTransport(handler))
    gw = Gateway(Settings(), gmail, FakeDetonator(verdict))
    asyncio.run(gw.setup())
    return gw, calls


def test_clean_mail_released_to_inbox():
    gw, calls = make_gateway(mail())
    assert asyncio.run(gw.process("m1")).action == "released"
    assert '"INBOX"' in calls[0]


def test_scam_verdict_blocks_without_inbox():
    gw, calls = make_gateway(mail("see https://evil.test/login"), "scam")
    assert asyncio.run(gw.process("m1")).action == "blocked"
    assert "INBOX" not in calls[0]


def test_uncertain_is_held_not_delivered():
    gw, calls = make_gateway(mail("see https://evil.test/login"), "uncertain")
    assert asyncio.run(gw.process("m1")).action == "held"
    assert "INBOX" not in calls[0]


def test_safe_verdict_releases():
    gw, _ = make_gateway(mail("see https://news.test/a"), "safe")
    assert asyncio.run(gw.process("m1")).action == "released"
