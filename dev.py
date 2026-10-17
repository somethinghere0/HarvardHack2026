#!/usr/bin/env python3
"""Run the whole Honeybank stack locally, no Docker. Starts (in order): the bundled fake Nessie
upstream (unless NESSIE_FAKE=0), the auth proxy, the orchestrator, and a dev gateway that serves the
frontend and reverse-proxies /bank-api and /api. With the defaults in .env.example every external
service is faked, so this runs with no keys.

    python dev.py          # then open http://localhost:3000  (bank)  and  /ops.html  (fraud monitor)

Ctrl+C stops everything. Requires: fastapi uvicorn httpx argon2-cffi  (pip install those, or the two
requirements files). Real integrations additionally need the packages in backend/requirements.txt."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import urllib.request

ROOT = Path(__file__).resolve().parent
PY = sys.executable

PORTS = {"nessie": 9000, "proxy": 8000, "orch": 8001, "gateway": 3000}


def load_dotenv() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if v and v[0] in "\"'" and v[-1:] == v[0]:
            v = v[1:-1]                       # strip matching quotes
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()  # strip inline comment
        os.environ.setdefault(k.strip(), v)


def _is_public(url: str) -> bool:
    """A URL a remote service (real Nessie) could actually reach — i.e. not localhost."""
    return bool(url) and not any(h in url for h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"))


def env(**over) -> dict:
    e = dict(os.environ)
    e.setdefault("PYTHONUNBUFFERED", "1")
    e.update({k: str(v) for k, v in over.items()})
    return e


def wait_health(url: str, name: str, tries: int = 60) -> None:
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.4)
    print(f"!! {name} did not become healthy at {url}")


def main() -> None:
    load_dotenv()
    datadir = ROOT / ".devdata"
    datadir.mkdir(exist_ok=True)

    fake = os.environ.get("NESSIE_FAKE", "1").lower() in ("1", "true", "yes", "on")
    nessie_base = f"http://127.0.0.1:{PORTS['nessie']}" if fake else \
        os.environ.get("NESSIE_BASE_URL", "https://v2-prod-api.nessieisreal.com")
    nessie_key = os.environ.get("NESSIE_API_KEY", "") or "fake-local-key"
    internal = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")
    user_public = os.environ.get("PUBLIC_URL", "").strip()
    tunnel_token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
    # In FAKE mode the bundled upstream can reach localhost, so default the webhook URL to the gateway.
    # In LIVE mode only a real (public) URL works, so pass the user's PUBLIC_URL through untouched; if
    # it's blank the orchestrator polls GET /events instead.
    public_url = user_public or (f"http://127.0.0.1:{PORTS['gateway']}" if fake else "")

    procs: list[subprocess.Popen] = []

    def spawn(name, args, cwd, environ):
        print(f"→ starting {name} (:{PORTS.get(name,'?')})")
        procs.append(subprocess.Popen(args, cwd=cwd, env=environ))

    try:
        if fake:
            spawn("nessie", [PY, "-m", "uvicorn", "app.fake_nessie:app", "--port", str(PORTS["nessie"])],
                  ROOT / "backend", env())
            wait_health(f"http://127.0.0.1:{PORTS['nessie']}/health", "fake-nessie")

        spawn("proxy", [PY, "-m", "uvicorn", "app.main:app_factory", "--factory", "--port", str(PORTS["proxy"])],
              ROOT / "proxy", env(
                  NESSIE_API_KEY=nessie_key, NESSIE_BASE_URL=nessie_base,
                  DB_PATH=str(datadir / "proxy.db"), OTP_REQUIRED="1", ENFORCE_CUSTOMER_SCOPE="1",
                  ORCHESTRATOR_URL=f"http://127.0.0.1:{PORTS['orch']}", INTERNAL_SECRET=internal,
                  AUTH_RATE_LIMIT="1000"))
        wait_health(f"http://127.0.0.1:{PORTS['proxy']}/health", "proxy")

        spawn("orch", [PY, "-m", "uvicorn", "app.main:app", "--port", str(PORTS["orch"])],
              ROOT / "backend", env(
                  ORCH_DB_PATH=str(datadir / "orchestrator.db"),
                  PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}", INTERNAL_SECRET=internal,
                  NESSIE_BASE_URL=nessie_base, NESSIE_API_KEY=nessie_key,
                  NESSIE_FAKE="1" if fake else "0", PUBLIC_URL=public_url))
        wait_health(f"http://127.0.0.1:{PORTS['orch']}/health", "orchestrator")

        spawn("gateway", [PY, "-m", "uvicorn", "dev_gateway:app", "--port", str(PORTS["gateway"])],
              ROOT, env(FRONTEND_DIR=str(ROOT / "frontend"),
                        DEV_PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}",
                        DEV_ORCH_URL=f"http://127.0.0.1:{PORTS['orch']}"))
        wait_health(f"http://127.0.0.1:{PORTS['gateway']}/", "gateway")

        # Cloudflare tunnel: launch from the token so real Nessie webhooks can reach this machine.
        # Opt-in only: set START_TUNNEL=1 to have dev.py run a named tunnel from your token. If you
        # run your own tunnel (e.g. `cloudflared tunnel --url http://localhost:3000`), leave this off
        # and just set PUBLIC_URL to the printed URL.
        import shutil
        start_tunnel = os.environ.get("START_TUNNEL", "0").lower() in ("1", "true", "yes", "on")
        if start_tunnel and tunnel_token:
            if not shutil.which("cloudflared"):
                print("!! START_TUNNEL set but `cloudflared` isn't installed (brew install cloudflared).")
            else:
                print("→ starting cloudflared tunnel from token")
                procs.append(subprocess.Popen(
                    ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token],
                    env=env()))

        webhook_note = ""
        if not fake:
            if _is_public(public_url):
                webhook_note = f"    Webhooks:       {public_url}/api/webhooks/nessie"
            else:
                webhook_note = ("    Webhooks:       polling GET /events (set PUBLIC_URL to your "
                                "tunnel hostname for push)")
        if tunnel_token and not user_public:
            print("!! Tunnel token set but PUBLIC_URL is empty — set PUBLIC_URL to your tunnel's "
                  "hostname (e.g. https://honeybank.example.com) so webhooks are delivered.\n")

        print("\n  Honeybank is up:")
        print(f"    Bank (bait):    http://localhost:{PORTS['gateway']}/")
        print(f"    Fraud monitor:  http://localhost:{PORTS['gateway']}/ops.html")
        print(f"    Mode: Nessie={'FAKE' if fake else 'LIVE'}  (Ctrl+C to stop)")
        if webhook_note:
            print(webhook_note)
        print()
        while True:
            time.sleep(1)
            for p in procs:
                if p.poll() is not None:
                    raise SystemExit(f"A service exited (pid {p.pid}, code {p.returncode}).")
    except (KeyboardInterrupt, SystemExit) as e:
        if str(e):
            print(e)
    finally:
        print("stopping…")
        for p in procs:
            try:
                p.send_signal(signal.SIGINT)
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


if __name__ == "__main__":
    main()
