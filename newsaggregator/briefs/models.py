"""Core data types for the BriefSnap daily brief pipeline (V9)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Candidate:
    """One article discovered from a feed, before clustering."""

    url: str
    title: str
    topic: str
    source: str = ""
    description: str = ""
    published_at: datetime | None = None
    image_url: str = ""
    feed_url: str = ""

    # Filled during enrichment
    content: str = ""
    scraped_image_url: str = ""

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse

        host = urlparse(self.url).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    @property
    def id(self) -> str:
        return hashlib.sha1(self.url.encode("utf-8")).hexdigest()[:16]

    @property
    def age_hours(self) -> float | None:
        if not self.published_at:
            return None
        delta = datetime.now(timezone.utc) - self.published_at
        return max(delta.total_seconds() / 3600.0, 0.0)

    @property
    def best_image_url(self) -> str:
        return self.scraped_image_url or self.image_url


@dataclass
class Cluster:
    """A story: one or more candidates covering the same event."""

    members: list[Candidate] = field(default_factory=list)
    score: float = 0.0

    @property
    def id(self) -> str:
        return self.lead.id

    @property
    def lead(self) -> Candidate:
        """Best single article to represent the story."""
        return self.members[0]

    @property
    def topic(self) -> str:
        # Majority topic across members; ties resolved by lead.
        counts: dict[str, int] = {}
        for member in self.members:
            counts[member.topic] = counts.get(member.topic, 0) + 1
        return max(counts, key=lambda t: (counts[t], t == self.lead.topic))

    @property
    def domains(self) -> set[str]:
        return {m.domain for m in self.members if m.domain}

    @property
    def sources(self) -> list[str]:
        seen: list[str] = []
        for member in self.members:
            name = member.source or member.domain
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def newest_published(self) -> datetime | None:
        dates = [m.published_at for m in self.members if m.published_at]
        return max(dates) if dates else None

    @property
    def newest_age_hours(self) -> float | None:
        newest = self.newest_published
        if not newest:
            return None
        delta = datetime.now(timezone.utc) - newest
        return max(delta.total_seconds() / 3600.0, 0.0)
