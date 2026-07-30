"""BriefSnap daily brief pipeline V9 — orchestrator.

Architecture: deterministic curation, LLM writing.

    gather -> screen -> cluster -> rank/select -> enrich
           -> write (Gemini, schema + feedback retry) -> validate -> publish

Selection (what's in the brief) is deterministic and auditable; the model
only writes copy over an already-curated packet. Compare V8, which asked
the model to select *and* write, then patched the output with ~1,650 lines
of repair heuristics.

Public surface kept compatible with the rest of the repo:
    DailyBriefPipeline, PipelineOptions, main(argv)
    DailyBriefPipeline.refresh_latest_firestore_sports_scores()
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests

from . import cluster as cluster_mod
from . import enrich as enrich_mod
from . import fetch as fetch_mod
from . import publish as publish_mod
from . import rank as rank_mod
from . import screen as screen_mod
from . import sports as sports_mod
from . import validate as validate_mod
from . import writer as writer_mod
from .config import (
    MIN_PUBLISHABLE_STORIES,
    TOPIC_NAMES,
    TOPIC_PRIORITY,
    TRUSTED_SOURCE_DOMAINS,
)
from .models import Cluster

__all__ = [
    "DailyBriefPipeline",
    "PipelineOptions",
    "TOPIC_PRIORITY",
    "main",
]


@dataclass
class PipelineOptions:
    dry_run: bool = False
    publish: bool = True
    skip_firestore: bool = False
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class DailyBriefPipeline:
    """Collect, write, and publish BriefSnap's daily brief."""

    def __init__(self, options: PipelineOptions | None = None):
        self.options = options or PipelineOptions()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "BriefSnapBot/3.0 (+https://briefsnap.com; daily brief aggregator)"
                )
            }
        )
        self.today_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Main run
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        start = time.time()

        candidates = fetch_mod.gather(self.session)
        kept, rejections = screen_mod.screen(candidates)
        print(f"Screened to {len(kept)} candidates (rejected: {rejections})")

        clusters = cluster_mod.build_clusters(kept)
        selected = rank_mod.select(clusters)
        selected = enrich_mod.enrich(selected)

        if len(selected) < MIN_PUBLISHABLE_STORIES:
            raise RuntimeError(
                f"Only {len(selected)} publishable stories after enrichment; "
                f"need {MIN_PUBLISHABLE_STORIES}. Refusing to publish a thin brief."
            )

        if not self.options.dry_run and not self.options.skip_firestore:
            sports_mod.archive_stale_firestore_scores()
        score_cards = sports_mod.fetch_top_sports_scores(self.session)

        if self.options.dry_run:
            copy_payload = self._dry_run_copy(selected)
            model_used = "dry-run"
        else:
            copy_payload, model = writer_mod.write_brief(
                selected,
                validate=validate_mod.validate_brief,
                model_override=self.options.model,
            )
            model_used = f"{model}-v9"

        brief = self._assemble(copy_payload, selected, score_cards, model_used)
        publish_mod.write_artifact(brief)

        if not self.options.dry_run and not self.options.skip_firestore and self.options.publish:
            publish_mod.publish_firestore(brief)
        else:
            print("Skipping Firestore publish (dry-run/skip flags)")

        elapsed = time.time() - start
        print(
            f"Done in {elapsed:.1f}s — {len(brief['stories'])} stories, "
            f"{len(brief['sections'])} sections, model {model_used}"
        )
        return brief

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------

    def _assemble(
        self,
        copy_payload: dict[str, Any],
        selected: list[Cluster],
        score_cards: list[dict[str, Any]],
        model_used: str,
    ) -> dict[str, Any]:
        copy_by_id = {str(story.get("id")): story for story in copy_payload.get("stories", [])}

        stories: list[dict[str, Any]] = []
        for cluster in selected:
            model_copy = copy_by_id.get(cluster.id, {})
            lead = cluster.lead
            stories.append(
                {
                    "id": cluster.id,
                    "topic": cluster.topic,
                    "title": str(model_copy.get("title") or lead.title),
                    "source": lead.source or lead.domain,
                    "url": lead.url,
                    "summary": str(model_copy.get("summary") or lead.description[:220]),
                    "why_it_matters": str(model_copy.get("why_it_matters") or ""),
                    "urgency": str(model_copy.get("urgency") or "medium"),
                    "published_at": lead.published_at.isoformat() if lead.published_at else None,
                    "image_url": lead.best_image_url or None,
                }
            )

        # Sections: keep the model's framing, re-anchor story_ids deterministically.
        priority = {topic: index for index, topic in enumerate(TOPIC_PRIORITY)}
        model_sections = {
            str(section.get("topic")): section
            for section in copy_payload.get("sections", [])
        }
        topics_present: list[str] = []
        for story in stories:
            if story["topic"] not in topics_present:
                topics_present.append(story["topic"])

        sections: list[dict[str, Any]] = []
        for topic in sorted(topics_present, key=lambda t: priority.get(t, 99)):
            model_section = model_sections.get(topic, {})
            story_ids = [story["id"] for story in stories if story["topic"] == topic]
            sections.append(
                {
                    "topic": topic,
                    "title": str(model_section.get("title") or TOPIC_NAMES.get(topic, topic)),
                    "summary": str(model_section.get("summary") or ""),
                    "why_it_matters": str(model_section.get("why_it_matters") or ""),
                    "story_ids": story_ids,
                }
            )

        hero_image_url = self._hero_image_url(
            str(copy_payload.get("headline") or ""), stories
        )

        all_members = [member for cluster in selected for member in cluster.members]
        trusted_leads = sum(
            1 for cluster in selected if cluster.lead.domain in TRUSTED_SOURCE_DOMAINS
        )
        coverage_report = {
            "source_packet_count": len(all_members),
            "source_packet_domains": len({m.domain for m in all_members if m.domain}),
            "story_count": len(stories),
            "leading_trusted_story_count": trusted_leads,
            "story_image_count": sum(1 for story in stories if story.get("image_url")),
            "sports_story_count": sum(1 for story in stories if story["topic"] == "SPORTS"),
            "story_topic_counts": {
                topic: sum(1 for story in stories if story["topic"] == topic)
                for topic in topics_present
            },
        }

        brief: dict[str, Any] = {
            "id": self.today_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_used": model_used,
            "headline": str(copy_payload.get("headline") or ""),
            "dek": str(copy_payload.get("dek") or ""),
            "summary": str(copy_payload.get("summary") or ""),
            "quick_hits": [str(hit) for hit in copy_payload.get("quick_hits", [])],
            "hero_image_url": hero_image_url,
            "sections": sections,
            "custom_widgets": [],
            "stories": stories,
            "sports_scores": score_cards,
            "source_count": coverage_report["source_packet_count"],
            "coverage_report": coverage_report,
        }
        brief.update(sports_mod.sports_scores_metadata(score_cards))
        return brief

    @staticmethod
    def _hero_image_url(headline: str, stories: list[dict[str, Any]]) -> str | None:
        """Hero art should match the lede: prefer the story whose title
        overlaps the headline most, then any imaged story."""
        from .cluster import similarity, tokens

        headline_tokens = tokens(headline)
        best_url, best_overlap = None, 0.0
        for story in stories:
            if not story.get("image_url"):
                continue
            overlap = similarity(headline_tokens, tokens(str(story["title"])))
            if overlap > best_overlap:
                best_url, best_overlap = story["image_url"], overlap
        if best_url and best_overlap >= 0.3:
            return best_url
        return next(
            (story["image_url"] for story in stories if story.get("image_url")), None
        )

    def _dry_run_copy(self, selected: list[Cluster]) -> dict[str, Any]:
        """Deterministic placeholder copy so --dry-run needs no API keys."""
        return {
            "headline": selected[0].lead.title,
            "dek": "Dry-run edition assembled without model copy.",
            "summary": (
                "Dry-run brief. Story selection and enrichment ran; "
                "prose generation was skipped."
            ),
            "quick_hits": [cluster.lead.title for cluster in selected[:5]],
            "sections": [],
            "stories": [
                {
                    "id": cluster.id,
                    "title": cluster.lead.title,
                    "summary": cluster.lead.description[:200] or cluster.lead.title,
                    "why_it_matters": "",
                    "urgency": "medium",
                }
                for cluster in selected
            ],
        }

    # ------------------------------------------------------------------
    # Sports score refresh (used by main_sports.py / main_live_sports.py)
    # ------------------------------------------------------------------

    def refresh_latest_firestore_sports_scores(self) -> dict[str, Any]:
        sports_mod.archive_stale_firestore_scores()
        score_cards = sports_mod.fetch_top_sports_scores(self.session)[:6]
        metadata = sports_mod.sports_scores_metadata(score_cards)
        return publish_mod.refresh_latest_sports_scores(score_cards, metadata)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BriefSnap daily brief pipeline (V9)")
    parser.add_argument("--dry-run", action="store_true", help="Skip Gemini and Firestore")
    parser.add_argument("--skip-firestore", action="store_true", help="Generate but do not publish")
    parser.add_argument("--model", help="Override the Gemini model")
    args = parser.parse_args(argv)

    options = PipelineOptions(
        dry_run=args.dry_run,
        skip_firestore=args.skip_firestore,
        model=args.model,
    )
    try:
        DailyBriefPipeline(options).run()
    except Exception as exc:
        print(f"ERROR: BriefSnap pipeline failed: {exc}")
        import traceback

        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
