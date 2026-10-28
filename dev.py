#!/usr/bin/env python3
"""Run the whole Honeybank stack locally (no Docker): auth proxy, orchestrator, email-firewall watcher, and a
gateway that serves the frontend and reverse-proxies /bank-api and /api. Everything is live
— it needs the real keys in .env (at minimum NESSIE_API_KEY; ANTHROPIC_API_KEY + DAYTONA_API_KEY +
a public PUBLIC_URL to run the sandboxed agent).

    python dev.py        # then open http://localhost:3000/ (bank) and /ops.html (fraud monitor)

Tunnel (TUNNEL=ngrok|cloudflared|none, default ngrok when it's installed): dev.py reuses an ngrok
already forwarding :3000 or starts one (on NGROK_DOMAIN, or the ngrok host in PUBLIC_URL, for a stable
address), then hands the live URL to the orchestrator as PUBLIC_URL.

Ctrl+C stops everything."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
PORTS = {"proxy": 8000, "orch": 8001, "gateway": 3000}


def _is_public(url: str) -> bool:
    return bool(url) and not any(h in url for h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"))


def load_dotenv() -> None:
    # .env.local overrides .env (loaded first; setdefault keeps the first non-shadowed value).
    for name in (".env.local", ".env"):
        f = ROOT / name
        if not f.exists():
            continue
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
            if v:  # don't let an empty override mask a real value in the other file
                os.environ.setdefault(k.strip(), v)


def env(**over) -> dict:
    e = dict(os.environ)
    e.setdefault("PYTHONUNBUFFERED", "1")
    # macOS python.org builds ship no CA bundle, so outbound TLS (Daytona API, Gmail SMTP) fails with
    # CERTIFICATE_VERIFY_FAILED. Point OpenSSL/requests at certifi's bundle.
    try:
        import certifi
        e.setdefault("SSL_CERT_FILE", certifi.where())
        e.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except Exception:
        pass
    e.update({k: str(v) for k, v in over.items()})
    return e


def wait_health(url: str, name: str, proc: subprocess.Popen, tries: int = 60) -> None:
    for _ in range(tries):
        if proc.poll() is not None:  # died (e.g. port taken) — don't mistake someone else's server for ours
            raise SystemExit(f"{name} exited during startup (code {proc.returncode}).")
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except Exception:
            time.sleep(0.4)
    print(f"!! {name} did not become healthy at {url}")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _cmdline(pid: int) -> str:
    try:
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _port_owners(port: int) -> list[int]:
    try:
        out = subprocess.run(["lsof", "-t", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    return [int(x) for x in out.split() if x.strip().isdigit()]


def _stop(pids: list[int], timeout: float = 8) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    deadline = time.time() + timeout
    while time.time() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.2)
    for pid in pids:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def take_over(datadir: Path) -> None:
    """Stop a previous Honeybank run (another terminal, an orphaned launch) so its servers don't hold our
    ports. Only our own processes are stopped; anything else on a port is reported, not killed."""
    pidfile = datadir / "dev.pid"
    try:
        old = int(pidfile.read_text().strip())
    except Exception:
        old = 0
    if old and old != os.getpid() and _alive(old) and "dev.py" in _cmdline(old):
        print(f"→ stopping previous Honeybank run (pid {old})")
        _stop([old])
    ours = ("app.main:app", "dev_gateway:app")
    for name, port in PORTS.items():
        pids = _port_owners(port)
        if not pids:
            continue
        mine = [p for p in pids if any(m in _cmdline(p) for m in ours)]
        if mine:
            print(f"→ freeing :{port} from a leftover Honeybank {name} (pid {', '.join(map(str, mine))})")
            _stop(mine)
        others = [p for p in _port_owners(port)]
        if others:
            sys.exit(f"Port {port} ({name}) is in use by another program: "
                     f"{others[0]} {_cmdline(others[0])[:80]}\nStop it and run again.")
    # Orphaned watchers from an earlier run would double-process mail.
    try:
        out = subprocess.run(["pgrep", "-f", "backend/scripts/gmail_watcher.py"],
                             capture_output=True, text=True).stdout
        stray = [int(x) for x in out.split() if x.isdigit() and int(x) != os.getpid()]
        if stray:
            _stop(stray)
    except FileNotFoundError:
        pass
    pidfile.write_text(str(os.getpid()))


def _ngrok_tunnel(port: int) -> tuple[str, str]:
    """(https URL, upstream addr) of a running ngrok agent that forwards to `port`, or ('', '')."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1) as r:
            tunnels = json.load(r).get("tunnels", [])
    except Exception:
        return "", ""
    for t in tunnels:
        addr = str(t.get("config", {}).get("addr", ""))
        if t.get("public_url", "").startswith("https://") and addr.rstrip("/").endswith(f":{port}"):
            return t["public_url"].rstrip("/"), addr
    return "", ""


def start_ngrok(procs: list, public_url: str, datadir: Path) -> str:
    port = PORTS["gateway"]
    url, addr = _ngrok_tunnel(port)
    if url:
        print(f"→ reusing running ngrok tunnel {url}")
        if "localhost" in addr:
            print(f"   note: it forwards to {addr}; if you see ERR_NGROK_8012, restart it as "
                  f"`ngrok http 127.0.0.1:{port}` (or stop it and let dev.py start one)")
        return url
    if not shutil.which("ngrok"):
        print("!! TUNNEL=ngrok but ngrok isn't installed (brew install ngrok, then ngrok config add-authtoken <token>).")
        return public_url
    domain = os.environ.get("NGROK_DOMAIN", "").strip()
    if not domain and "ngrok" in public_url:
        domain = public_url  # keep the static domain the .env already points at
    # 127.0.0.1, not "localhost": uvicorn listens on IPv4 only, and ngrok resolving localhost to ::1
    # gives intermittent ERR_NGROK_8012 (upstream refused).
    args = ["ngrok", "http", f"127.0.0.1:{port}", "--log", str(datadir / "ngrok.log")]
    if domain:
        args += ["--url", domain if domain.startswith("http") else "https://" + domain]
    print("→ starting ngrok" + (f" on {domain}" if domain else ""))
    procs.append(subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env()))
    for _ in range(40):
        url, _ = _ngrok_tunnel(port)
        if url:
            return url
        if procs[-1].poll() is not None:
            break
        time.sleep(0.25)
    print(f"!! ngrok didn't come up — see {datadir / 'ngrok.log'} (authtoken set? domain yours? "
          "only one free ngrok agent can run at a time)")
    procs.pop()
    return public_url


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)  # status lines show up immediately even when piped
    load_dotenv()
    if not os.environ.get("NESSIE_API_KEY", "").strip():
        sys.exit("NESSIE_API_KEY is required in .env (everything is live now; there is no fake mode).")

    datadir = ROOT / ".devdata"
    datadir.mkdir(exist_ok=True)
    take_over(datadir)
    # Closing the terminal / kill sends SIGHUP/SIGTERM: shut the children down instead of orphaning them
    # (orphans keep the ports and break the next start).
    def _exit(*_):
        raise SystemExit("")
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, _exit)
    internal = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")
    public_url = os.environ.get("PUBLIC_URL", "").strip()
    procs: list[subprocess.Popen] = []
    side: list[subprocess.Popen] = []  # tunnels: losing one shouldn't take the stack down
    tunnel = os.environ.get("TUNNEL", "").strip().lower() or ("ngrok" if shutil.which("ngrok") else "none")

    def spawn(name, args, cwd, environ):
        print(f"→ starting {name}" + (f" (:{PORTS[name]})" if name in PORTS else ""))
        procs.append(subprocess.Popen(args, cwd=cwd, env=environ))
        return procs[-1]

    try:
        p = spawn("proxy", [PY, "-m", "uvicorn", "app.main:app_factory", "--factory", "--port", str(PORTS["proxy"])],
              ROOT / "proxy", env(DB_PATH=str(datadir / "proxy.db"), OTP_REQUIRED="1",
                                  ENFORCE_CUSTOMER_SCOPE="1", ORCHESTRATOR_URL=f"http://127.0.0.1:{PORTS['orch']}",
                                  INTERNAL_SECRET=internal, AUTH_RATE_LIMIT="1000"))
        wait_health(f"http://127.0.0.1:{PORTS['proxy']}/health", "proxy", p)

        if tunnel == "ngrok":
            url = start_ngrok(side, public_url, datadir)
            if public_url and url != public_url:
                print(f"   PUBLIC_URL in .env was {public_url}; using the live tunnel instead")
            public_url = url

        p = spawn("orch", [PY, "-m", "uvicorn", "app.main:app", "--port", str(PORTS["orch"])],
              ROOT / "backend", env(ORCH_DB_PATH=str(datadir / "orchestrator.db"),
                                    PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}", INTERNAL_SECRET=internal,
                                    PUBLIC_URL=public_url, ORCH_LOCAL_URL=f"http://127.0.0.1:{PORTS['orch']}",
                                    LOCAL_BANK_URL=f"http://127.0.0.1:{PORTS['gateway']}"))
        wait_health(f"http://127.0.0.1:{PORTS['orch']}/health", "orchestrator", p)

        p = spawn("gateway", [PY, "-m", "uvicorn", "dev_gateway:app", "--port", str(PORTS["gateway"])],
              ROOT, env(FRONTEND_DIR=str(ROOT / "frontend"),
                        DEV_PROXY_URL=f"http://127.0.0.1:{PORTS['proxy']}",
                        DEV_ORCH_URL=f"http://127.0.0.1:{PORTS['orch']}"))
        wait_health(f"http://127.0.0.1:{PORTS['gateway']}/", "gateway", p)

        # Email firewall: vet every inbound Gmail message (needs an app password).
        if os.environ.get("GMAIL_APP_PASSWORD", "").strip():
            spawn("watcher", [PY, "backend/scripts/gmail_watcher.py"], ROOT,
                  env(ORCHESTRATOR_URL=f"http://127.0.0.1:{PORTS['orch']}"))

        # TUNNEL=cloudflared: run a named cloudflared tunnel from CLOUDFLARE_TUNNEL_TOKEN (PUBLIC_URL must
        # be its hostname). START_TUNNEL=1 is the older spelling of the same thing.
        if (tunnel == "cloudflared" or os.environ.get("START_TUNNEL", "0").lower() in ("1", "true", "yes", "on")) \
                and os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", "").strip():
            if shutil.which("cloudflared"):
                print("→ starting cloudflared tunnel from token")
                side.append(subprocess.Popen(
                    ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token",
                     os.environ["CLOUDFLARE_TUNNEL_TOKEN"].strip()], env=env()))
            else:
                print("!! START_TUNNEL set but cloudflared isn't installed (brew install cloudflared).")

        print("\n  Honeybank is up (LIVE):")
        print(f"    Bank (bait):    http://localhost:{PORTS['gateway']}/")
        print(f"    Fraud monitor:  http://localhost:{PORTS['gateway']}/ops.html")
        if public_url and _is_public(public_url):
            print(f"    Public (tunnel): {public_url}/   ← put this link in the scam email")
            print(f"    Public monitor:  {public_url}/ops.html")
        else:
            print("    No public tunnel — the agent runs locally and webhooks fall back to polling. "
                  "Install ngrok (or set PUBLIC_URL) for the full flow.")
        print(f"    Agent runtime:  {os.environ.get('AGENT_RUNTIME', 'auto')}")
        print("    (Ctrl+C to stop)\n")
        while True:
            time.sleep(1)
            for p in procs:
                if p.poll() is not None:
                    raise SystemExit(f"A service exited (pid {p.pid}, code {p.returncode}).")
            for p in list(side):
                if p.poll() is not None:
                    side.remove(p)
                    print(f"!! tunnel exited (code {p.returncode}) — the public URL is down until you restart.")
    except (KeyboardInterrupt, SystemExit) as e:
        if str(e):
            print(e)
    finally:
        print("stopping…")
        for p in procs + side:
            try:
                p.send_signal(signal.SIGINT)
            except Exception:
                pass
        for p in procs + side:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        try:
            if (datadir / "dev.pid").read_text().strip() == str(os.getpid()):
                (datadir / "dev.pid").unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
