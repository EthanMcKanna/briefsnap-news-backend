"""Enrichment: scrape only the selected stories.

Resolves Google News redirect URLs, extracts body text for grounding the
writer, and picks a validated article image. Runs after selection so we
scrape ~20 pages per run instead of hundreds.
"""

from __future__ import annotations

import concurrent.futures

from newsaggregator.fetchers.article_fetcher import ArticleFetcher

from .config import SCRAPE_WORKERS
from .models import Cluster
from .screen import canonical_url

_EXCERPT_CHARS = 700


def _enrich_cluster(cluster: Cluster) -> None:
    lead = cluster.lead

    # Resolve Google News redirect to the real publisher URL.
    if "news.google.com" in lead.url:
        real_url = ArticleFetcher.extract_real_url_from_google(lead.url)
        if real_url:
            lead.url = canonical_url(real_url)
        else:
            # Unresolvable redirect: fall back to a member with a direct URL.
            for member in cluster.members[1:]:
                if "news.google.com" not in member.url:
                    cluster.members.remove(member)
                    cluster.members.insert(0, member)
                    lead = member
                    break
            else:
                return

    content, publish_date = ArticleFetcher.scrape_article_content(lead.url)
    if content:
        lead.content = content
        if publish_date and not lead.published_at:
            try:
                from datetime import timezone

                if publish_date.tzinfo is None:
                    publish_date = publish_date.replace(tzinfo=timezone.utc)
                lead.published_at = publish_date
            except (TypeError, ValueError):
                pass

    image_candidates = [lead.image_url] if lead.image_url else []
    image_candidates += ArticleFetcher.find_article_images(lead.url)
    best = ArticleFetcher.select_best_image(image_candidates)
    if best:
        lead.scraped_image_url = best


def enrich(clusters: list[Cluster]) -> list[Cluster]:
    """Scrape lead articles in parallel; drop clusters that end up empty."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=SCRAPE_WORKERS) as pool:
        list(pool.map(_enrich_cluster, clusters))

    usable = [
        cluster
        for cluster in clusters
        if cluster.lead.content or len(cluster.lead.description) >= 60
    ]
    scraped = sum(1 for cluster in usable if cluster.lead.content)
    with_images = sum(1 for cluster in usable if cluster.lead.best_image_url)
    print(
        f"Enriched {len(usable)}/{len(clusters)} stories "
        f"({scraped} full text, {with_images} images)"
    )
    return usable


def excerpt(cluster: Cluster) -> str:
    """Grounding text for the writer: scraped body first, else description."""
    lead = cluster.lead
    text = lead.content or lead.description
    text = " ".join(text.split())
    return text[:_EXCERPT_CHARS]
