from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Verdict = Literal["safe", "scam", "uncertain"]


@dataclass
class Detonation:
    verdict: Verdict
    evidence: list[str] = field(default_factory=list)
    destinations: list[str] = field(default_factory=list)  # URLs the page posted our decoy data to
    screenshots: list[str] = field(default_factory=list)  # base64 JPEG


class Detonator(Protocol):
    async def detonate(self, urls: list[str], triage_flags: list[str] | None = None) -> Detonation: ...


class HoldAllDetonator:
    """Used when no Daytona key is configured: every link is unverified, so the mail stays held."""

    async def detonate(self, urls: list[str], triage_flags: list[str] | None = None) -> Detonation:
        return Detonation("uncertain", ["sandbox not configured"])
