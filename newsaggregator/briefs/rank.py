"""Cluster scoring and diverse selection.

Importance = cross-outlet consensus + source tier + freshness.
Selection honors per-topic targets and domain caps but never pads a topic
with weak clusters: relevance beats quota.
"""

from __future__ import annotations

import math

from .config import (
    MAX_STORIES_PER_DOMAIN,
    MAX_STORIES_PER_TOPIC,
    MIN_CLUSTER_SCORE,
    STORY_BUDGET,
    TOPIC_PRIORITY,
    TOPIC_TARGETS,
    TRUSTED_SOURCE_DOMAINS,
)
from .cluster import similarity, tokens
from .models import Cluster

# Two clusters that both survived clustering can still be the same story
# phrased differently; at selection time a softer overlap kills the repeat.
_NEAR_DUP_SIMILARITY = 0.34
_TITLE_DUP_SIMILARITY = 0.45


def score_cluster(cluster: Cluster) -> float:
    trusted_domains = [
        domain for domain in cluster.domains if domain in TRUSTED_SOURCE_DOMAINS
    ]
    consensus = 3.2 * math.log2(1 + len(trusted_domains))
    max_tier = max(
        (TRUSTED_SOURCE_DOMAINS.get(domain, 0) for domain in cluster.domains),
        default=0,
    )
    tier_bonus = 0.35 * max_tier

    age = cluster.newest_age_hours
    if age is None:
        recency = 0.0
    elif age <= 3:
        recency = 3.0
    elif age <= 9:
        recency = 2.2
    elif age <= 18:
        recency = 1.4
    elif age <= 30:
        recency = 0.6
    else:
        recency = -1.0

    lead = cluster.lead
    quality = 0.0
    if len(lead.description) >= 80:
        quality += 0.5
    if lead.best_image_url:
        quality += 0.4

    # A story only one non-tier-1 outlet bothered to cover usually is not
    # part of "what you need to know".
    solo_penalty = 0.0
    if len(cluster.members) == 1 and max_tier < 8:
        solo_penalty = 1.5

    return consensus + tier_bonus + recency + quality - solo_penalty


def select(clusters: list[Cluster]) -> list[Cluster]:
    """Pick the day's stories with topic and domain diversity."""
    for cluster in clusters:
        cluster.score = score_cluster(cluster)

    eligible = sorted(
        (c for c in clusters if c.score >= MIN_CLUSTER_SCORE),
        key=lambda c: c.score,
        reverse=True,
    )

    selected: list[Cluster] = []
    selected_tokens: list[tuple[frozenset[str], frozenset[str]]] = []
    topic_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}

    def cluster_tokens(cluster: Cluster) -> tuple[frozenset[str], frozenset[str]]:
        lead = cluster.lead
        return (
            tokens(f"{lead.title} {lead.description[:200]}"),
            tokens(lead.title),
        )

    def try_take(cluster: Cluster, topic_cap: int) -> bool:
        topic = cluster.topic
        lead_domain = cluster.lead.domain
        if topic_counts.get(topic, 0) >= topic_cap:
            return False
        if domain_counts.get(lead_domain, 0) >= MAX_STORIES_PER_DOMAIN:
            return False
        full_tokens, title_tokens = cluster_tokens(cluster)
        for existing_full, existing_title in selected_tokens:
            if similarity(full_tokens, existing_full) >= _NEAR_DUP_SIMILARITY:
                return False
            if similarity(title_tokens, existing_title) >= _TITLE_DUP_SIMILARITY:
                return False
        selected.append(cluster)
        selected_tokens.append((full_tokens, title_tokens))
        topic_counts[topic] = topic_counts.get(topic, 0) + 1
        domain_counts[lead_domain] = domain_counts.get(lead_domain, 0) + 1
        return True

    # Pass 1: fill per-topic targets with the strongest clusters.
    for cluster in eligible:
        if len(selected) >= STORY_BUDGET:
            break
        target = TOPIC_TARGETS.get(cluster.topic, 1)
        if cluster in selected:
            continue
        try_take(cluster, target)

    # Pass 2: backfill remaining budget with the best leftovers, any topic.
    for cluster in eligible:
        if len(selected) >= STORY_BUDGET:
            break
        if cluster in selected:
            continue
        try_take(cluster, MAX_STORIES_PER_TOPIC)

    # Deterministic presentation order: topic priority, then score.
    priority = {topic: index for index, topic in enumerate(TOPIC_PRIORITY)}
    selected.sort(key=lambda c: (priority.get(c.topic, 99), -c.score))

    summary = {}
    for cluster in selected:
        summary[cluster.topic] = summary.get(cluster.topic, 0) + 1
    print(f"Selected {len(selected)} stories: {summary}")
    return selected
