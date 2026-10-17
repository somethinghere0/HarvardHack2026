#!/usr/bin/env python3
"""Run the whole Honeybank stack locally (no Docker): auth proxy, orchestrator, decoy portal, and a
gateway that serves the frontend and reverse-proxies /bank-api, /api and /portal. Everything is live
— it needs the real keys in .env (at minimum NESSIE_API_KEY; ANTHROPIC_API_KEY + DAYTONA_API_KEY +
a public PUBLIC_URL to run the sandboxed agent).

    python dev.py        # then open http://localhost:3000/ (bank) and /ops.html (fraud monitor)

Ctrl+C stops everything."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
PORTS = {"proxy": 8000, "orch": 8001, "portal": 8080, "gateway": 3000}


def _is_public(url: str) -> bool:
    return bool(url) and not any(h in url for h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"))


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
            v = v[1:-1]
        elif " #" in v:
            v = v.split(" #", 1)[0].rstrip()
        os.environ.setdefault(k.strip(), v)


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
    if not os.environ.get("NESSIE_API_KEY", "").strip():
        sys.exit("NESSIE_API_KEY is required in .env (everything is live now; there is no fake mode).")

    datadir = ROOT / ".devdata"
    datadir.mkdir(exist_ok=True)
    internal = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")
    public_url = os.environ.get("PUBLIC_URL", "").strip()
    portal_public = os.environ.get("PORTAL_URL", "").strip() or (f"{public_url}/portal" if public_url else "")
    procs: list[subprocess.Popen] = []

    def spawn(name, args, cwd, environ):
        print(f"→ starting {name} (:{PORTS.get(name, '?')})")
        procs.append(subprocess.Popen(args, cwd=cwd, env=environ))

    try:
        spawn("proxy", [PY, "-m", "uvicorn", "app.main:app_factory", "--factory", "--port", str(PORTS["proxy"])],
              ROOT / "proxy", env(DB_PATH=str(datadir / "proxy.db"), OTP_REQUIRED="1",
                                  ENFORCE_CUSTOMER_SCOPE="1", ORCHESTRATOR_URL=f"http://127.0.0.1:{PORTS['orch']}",
                                  INTERNAL_SECRET=internal, AUTH_RATE_LIMIT="1000"))
        wait_health(f"http://127.0.0.1:{PORTS['proxy']}/health", "proxy")

        spawn("orch", [PY, "-m", "uvicorn", "app.main:app", "--port", str(PORTS["orch"])],
              ROOT / "backend", env(ORCH_DB_PATH=str(datadir / "orchestrator.db"),
                                    PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}", INTERNAL_SECRET=internal,
                                    PUBLIC_URL=public_url, PORTAL_URL=portal_public))
        wait_health(f"http://127.0.0.1:{PORTS['orch']}/health", "orchestrator")

        spawn("portal", [PY, "-m", "uvicorn", "app:app", "--port", str(PORTS["portal"])],
              ROOT / "portal", env(PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}",
                                   ORCHESTRATOR_URL=f"http://127.0.0.1:{PORTS['orch']}", INTERNAL_SECRET=internal))
        wait_health(f"http://127.0.0.1:{PORTS['portal']}/health", "portal")

        spawn("gateway", [PY, "-m", "uvicorn", "dev_gateway:app", "--port", str(PORTS["gateway"])],
              ROOT, env(FRONTEND_DIR=str(ROOT / "frontend"),
                        DEV_PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}",
                        DEV_ORCH_URL=f"http://127.0.0.1:{PORTS['orch']}",
                        DEV_PORTAL_URL=f"http://127.0.0.1:{PORTS['portal']}"))
        wait_health(f"http://127.0.0.1:{PORTS['gateway']}/", "gateway")

        # Optional: run a named cloudflared tunnel from a token (START_TUNNEL=1). If you run your own
        # quick tunnel, leave this off and set PUBLIC_URL to the printed URL.
        import shutil
        if os.environ.get("START_TUNNEL", "0").lower() in ("1", "true", "yes", "on") \
                and os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip():
            if shutil.which("cloudflared"):
                print("→ starting cloudflared tunnel from token")
                procs.append(subprocess.Popen(
                    ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token",
                     os.environ["CLOUDFLARE_TUNNEL_TOKEN"].strip()], env=env()))
            else:
                print("!! START_TUNNEL set but cloudflared isn't installed (brew install cloudflared).")

        print("\n  Honeybank is up (LIVE):")
        print(f"    Bank (bait):    http://localhost:{PORTS['gateway']}/")
        print(f"    Fraud monitor:  http://localhost:{PORTS['gateway']}/ops.html")
        print(f"    Decoy portal:   http://localhost:{PORTS['gateway']}/portal")
        if public_url and _is_public(public_url):
            print(f"    Public (tunnel): {public_url}   (webhooks + sandbox agent use this)")
        else:
            print("    PUBLIC_URL not set to a public tunnel — the Daytona agent can't run; "
                  "webhooks fall back to polling. Set PUBLIC_URL for the full flow.")
        print("    (Ctrl+C to stop)\n")
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
