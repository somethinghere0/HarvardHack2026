from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from importlib import resources
from urllib.parse import urlparse

from daytona import AsyncDaytona, CreateSandboxFromImageParams, DaytonaConfig, Image, Resources

from .detonation import Detonation
from .persona import PersonaFactory
from .verdict import analyze

log = logging.getLogger("detonator")
MAX_URLS = 3


def safe_url(url: str) -> bool:
    """Only public http(s) URLs. The sandbox is isolated, but we still refuse internal targets and metadata IPs."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        for info in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


def sandbox_image() -> Image:
    return (Image.debian_slim("3.12")
            .env({"PLAYWRIGHT_BROWSERS_PATH": "/opt/pw"})
            .pip_install("playwright==1.49.0")
            .run_commands("playwright install --with-deps chromium"))


class DaytonaDetonator:
    """Opens each link in a fresh, disposable Daytona sandbox with headless Chromium, feeding the page decoy data."""

    def __init__(self, api_key: str, personas: PersonaFactory, api_url: str | None = None,
                 timeout_s: int = 150, max_parallel: int = 3):
        self._cfg = DaytonaConfig(api_key=api_key, api_url=api_url) if api_url else DaytonaConfig(api_key=api_key)
        self.personas, self.timeout_s = personas, timeout_s
        self._slots = asyncio.Semaphore(max_parallel)
        self._runner = resources.files("app.sandbox").joinpath("runner.py").read_bytes()

    async def detonate(self, urls: list[str], triage_flags: list[str] | None = None) -> Detonation:
        loop = asyncio.get_running_loop()
        checked = [u for u in urls if await loop.run_in_executor(None, safe_url, u)][:MAX_URLS]
        if not checked:
            return Detonation("uncertain", ["no safe public URL to open"])
        persona = await self.personas.new()
        try:
            async with self._slots:
                report = await asyncio.wait_for(self._run(checked, persona.for_sandbox()), self.timeout_s)
        except Exception as e:
            log.exception("detonation failed")
            return Detonation("uncertain", [f"sandbox error: {type(e).__name__}"])
        d = analyze(report, triage_flags)
        d.evidence.append(f"decoy persona canary {persona.canary}"
                          + (f", Nessie customer {persona.nessie_customer_id}" if persona.nessie_customer_id else ""))
        return d

    async def _run(self, urls: list[str], persona: dict) -> dict:
        daytona = AsyncDaytona(self._cfg)
        sandbox = None
        try:
            sandbox = await daytona.create(
                CreateSandboxFromImageParams(
                    image=sandbox_image(), ephemeral=True, auto_stop_interval=5, auto_delete_interval=10,
                    labels={"app": "scam-gateway"}, resources=Resources(cpu=2, memory=4, disk=5)),
                timeout=300)
            await sandbox.fs.upload_file(self._runner, "/tmp/runner.py")
            await sandbox.fs.upload_file(json.dumps({"urls": urls, "persona": persona}).encode(), "/tmp/job.json")
            res = await sandbox.process.exec("python /tmp/runner.py /tmp/job.json",
                                             env={"PLAYWRIGHT_BROWSERS_PATH": "/opt/pw"}, timeout=self.timeout_s - 20)
            for line in reversed((res.result or "").splitlines()):
                if line.startswith("REPORT:"):
                    return json.loads(line[len("REPORT:"):])
            raise RuntimeError(f"runner produced no report (exit {res.exit_code})")
        finally:
            if sandbox is not None:
                try:
                    await sandbox.delete()
                except Exception:
                    log.warning("failed to delete sandbox %s", getattr(sandbox, "id", "?"))
            await daytona.close()
