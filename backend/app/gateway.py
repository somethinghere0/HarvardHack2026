from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .config import Settings
from .detonation import Detonator
from .gmail import GmailClient
from .triage import triage

log = logging.getLogger("gateway")


@dataclass
class Decision:
    message_id: str
    sender: str
    subject: str
    action: str  # released | blocked | held
    reason: str
    urls: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    destinations: list[str] = field(default_factory=list)
    screenshot: str | None = None
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Gateway:
    def __init__(self, settings: Settings, gmail: GmailClient, detonator: Detonator):
        self.s, self.gmail, self.detonator = settings, gmail, detonator
        self.decisions: deque[Decision] = deque(maxlen=200)

    async def setup(self) -> None:
        await self.gmail.ensure_labels([self.s.quarantine_label, self.s.held_label, self.s.scam_label])
        await self.gmail.ensure_quarantine_filter(self.s.quarantine_label)

    async def process(self, message_id: str) -> Decision:
        t = triage(await self.gmail.get_raw(message_id), self.s.trusted_domains)
        base = dict(message_id=message_id, sender=t.sender, subject=t.subject, urls=t.urls)
        if t.clean:
            await self.gmail.release(message_id, self.s.quarantine_label)
            return Decision(**base, action="released", reason="no links and no red flags")
        if not t.urls:  # red flags but nothing to detonate: don't guess, keep it from the user
            await self.gmail.hold(message_id, self.s.held_label)
            return Decision(**base, action="held", reason="; ".join(t.flags), evidence=t.flags)
        d = await self.detonator.detonate(t.urls, t.flags)
        base.update(destinations=d.destinations, screenshot=self._save_screenshot(message_id, d.screenshots))
        if d.verdict == "safe":
            await self.gmail.release(message_id, self.s.quarantine_label)
            return Decision(**base, action="released", reason="links verified safe", evidence=d.evidence)
        if d.verdict == "scam":
            await self.gmail.block(message_id, self.s.quarantine_label, self.s.scam_label)
            return Decision(**base, action="blocked", reason="scam confirmed in sandbox", evidence=d.evidence + t.flags)
        await self.gmail.hold(message_id, self.s.held_label)
        return Decision(**base, action="held", reason="could not verify", evidence=d.evidence + t.flags)

    def _save_screenshot(self, message_id: str, shots: list[str]) -> str | None:
        if not shots:
            return None
        try:
            name = f"{message_id}.jpg"  # Gmail ids are hex, so safe as a filename
            Path(self.s.evidence_dir).mkdir(parents=True, exist_ok=True)
            (Path(self.s.evidence_dir) / name).write_bytes(base64.b64decode(shots[0]))
            return name
        except Exception:
            log.exception("could not save screenshot")
            return None

    async def run_once(self) -> list[Decision]:
        out = []
        for mid in await self.gmail.list_pending(self.s.quarantine_label, self.s.held_label):
            try:
                dec = await self.process(mid)
            except Exception:
                log.exception("failed processing %s; leaving it quarantined", mid)
                continue
            self.decisions.appendleft(dec)
            out.append(dec)
        return out

    async def run_forever(self) -> None:
        await self.setup()
        while True:
            try:
                await self.run_once()
            except Exception:
                log.exception("poll failed")
            await asyncio.sleep(self.s.poll_interval_s)

    def snapshot(self) -> list[dict]:
        return [asdict(d) for d in self.decisions]
