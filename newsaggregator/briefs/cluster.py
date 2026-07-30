"""Cross-source story clustering.

Same-story coverage from different outlets is grouped with union-find over
normalized token similarity. Cluster breadth (distinct trusted outlets)
becomes the pipeline's primary importance signal.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .config import CLUSTER_SIMILARITY, CLUSTER_WINDOW_HOURS, TRUSTED_SOURCE_DOMAINS
from .models import Candidate, Cluster

_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have he her his in is it its
    of on or say says said she that the their they this to was were will with
    after amid over new more than about into up out off just how why what when
    who where us""".split()
)

_TOKEN = re.compile(r"[a-z0-9']+")


def _stem(token: str) -> str:
    """Naive plural/possessive stem so "robots" matches "robot"."""
    token = token.rstrip("'")
    if token.endswith("'s"):
        token = token[:-2]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and not token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text: str) -> frozenset[str]:
    return frozenset(
        _stem(token)
        for token in _TOKEN.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    )


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return overlap / min(len(a), len(b))


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a


def _within_window(a: Candidate, b: Candidate) -> bool:
    if not a.published_at or not b.published_at:
        return True
    delta = abs((a.published_at - b.published_at).total_seconds()) / 3600.0
    return delta <= CLUSTER_WINDOW_HOURS


def _lead_sort_key(candidate: Candidate) -> tuple:
    """Best representative: trusted tier, substance, freshness."""
    tier = TRUSTED_SOURCE_DOMAINS.get(candidate.domain, 0)
    published = candidate.published_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        -tier,
        -len(candidate.description),
        -(published.timestamp()),
    )


def build_clusters(candidates: list[Candidate]) -> list[Cluster]:
    """Group candidates that cover the same story."""
    token_sets = [tokens(f"{c.title} {c.description[:200]}") for c in candidates]
    uf = _UnionFind(len(candidates))

    # Blocking on shared rare tokens keeps this O(n * bucket) rather than O(n^2).
    buckets: dict[str, list[int]] = {}
    for index, token_set in enumerate(token_sets):
        for token in token_set:
            buckets.setdefault(token, []).append(index)

    compared: set[tuple[int, int]] = set()
    for bucket in buckets.values():
        if len(bucket) > 60:  # ubiquitous token, useless for blocking
            continue
        for position, a in enumerate(bucket):
            for b in bucket[position + 1:]:
                pair = (a, b) if a < b else (b, a)
                if pair in compared:
                    continue
                compared.add(pair)
                if not _within_window(candidates[a], candidates[b]):
                    continue
                if similarity(token_sets[a], token_sets[b]) >= CLUSTER_SIMILARITY:
                    uf.union(a, b)

    grouped: dict[int, list[Candidate]] = {}
    for index, candidate in enumerate(candidates):
        grouped.setdefault(uf.find(index), []).append(candidate)

    clusters: list[Cluster] = []
    for members in grouped.values():
        members.sort(key=_lead_sort_key)
        clusters.append(Cluster(members=members))
    print(f"Clustered {len(candidates)} candidates into {len(clusters)} stories")
    return clusters
