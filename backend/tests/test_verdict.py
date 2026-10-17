from app.persona import PersonaFactory, generate
from app.verdict import analyze


def result(url="https://bank-login.test/", fields=(), submitted=True, requests=(), redirects=(), error=None):
    return {"url": url, "final_url": url, "title": "", "error": error, "redirects": list(redirects),
            "steps": [{"url": url, "fields": list(fields), "submitted": submitted}] if fields or not error else [],
            "requests": list(requests), "screenshot": None}


def post(url):
    return {"method": "POST", "url": url, "post": "x=1"}


def test_card_form_is_scam_and_destinations_recorded():
    d = analyze({"results": [result(fields=["card", "cvv", "email"], requests=[post("https://api.telegram.org/bot1/sendMessage")])]})
    assert d.verdict == "scam"
    assert d.destinations == ["https://api.telegram.org/bot1/sendMessage"]


def test_page_without_forms_is_safe():
    assert analyze({"results": [result(fields=[], submitted=False)]}).verdict == "safe"


def test_lone_login_form_uncertain_but_scam_with_triage_flags():
    r = {"results": [result(fields=["password", "email"])]}
    assert analyze(r).verdict == "uncertain"
    assert analyze(r, ["spf did not pass"]).verdict == "scam"


def test_login_posting_elsewhere_is_scam():
    r = {"results": [result(fields=["password", "email"], requests=[post("https://collector.evil.test/p.php")])]}
    assert analyze(r).verdict == "scam"


def test_unloadable_page_is_uncertain():
    assert analyze({"results": [result(error="TimeoutError")]}).verdict == "uncertain"


def test_any_scam_url_wins():
    r = {"results": [result(fields=[], submitted=False), result("https://x.test/", fields=["ssn"])]}
    assert analyze(r).verdict == "scam"


def test_persona_card_is_luhn_valid_and_unique_canary():
    a, b = generate(), generate("me@gmail.com")
    digits = [int(c) for c in a.card]
    assert (sum(digits[-1::-2]) + sum(sum(divmod(d * 2, 10)) for d in digits[-2::-2])) % 10 == 0
    assert a.canary != b.canary and b.email.startswith("me+") and a.card.startswith("400000")


def test_persona_without_proxy_login_is_local_only():
    import asyncio
    p = asyncio.run(PersonaFactory("http://proxy:8000").new())
    assert p.nessie_customer_id is None
