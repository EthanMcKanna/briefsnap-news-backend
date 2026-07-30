"""Release gate for the latest BriefSnap daily brief in Firestore.

Audits the already-published app payload: structure, copy completeness,
freshness, and sports score card sanity. Run in CI right after the pipeline
publishes, and before an iOS release.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from newsaggregator.briefs import sports as sports_mod
from newsaggregator.briefs.config import MIN_PUBLISHABLE_STORIES
from newsaggregator.briefs.pipeline import TOPIC_PRIORITY


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        date = value
    elif isinstance(value, str) and value.strip():
        try:
            date = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc)


def load_brief(args: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if args.brief_json:
        payload = json.loads(Path(args.brief_json).read_text())
        return str(payload.get("id") or args.brief_json), payload

    import firebase_admin
    from firebase_admin import firestore

    from newsaggregator.briefs.publish import firebase_credentials

    if not firebase_admin._apps:
        firebase_admin.initialize_app(firebase_credentials())
    db = firestore.client()

    if args.doc_id:
        doc = db.collection("daily_briefs").document(args.doc_id).get()
        if not doc.exists:
            raise SystemExit(f"daily_briefs/{args.doc_id} does not exist")
        return doc.id, doc.to_dict() or {}

    docs = list(
        db.collection("daily_briefs")
        .order_by("generated_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    if not docs:
        raise SystemExit("No daily_briefs documents found")
    return docs[0].id, docs[0].to_dict() or {}


def audit(doc_id: str, brief: dict[str, Any], max_age_hours: float) -> list[str]:
    problems: list[str] = []

    generated_at = parse_datetime(brief.get("generated_at"))
    if not generated_at:
        problems.append("generated_at missing or unparseable")
    else:
        age = datetime.now(timezone.utc) - generated_at
        if age > timedelta(hours=max_age_hours):
            problems.append(
                f"brief is {age.total_seconds() / 3600:.1f}h old (max {max_age_hours}h)"
            )

    model_used = str(brief.get("model_used") or "")
    if not model_used or model_used == "dry-run" or "fallback" in model_used:
        problems.append(f"model_used is not a real generated run: {model_used!r}")

    for text_field in ("headline", "dek", "summary"):
        if len(str(brief.get(text_field) or "").split()) < 4:
            problems.append(f"{text_field} is missing or too thin")

    quick_hits = brief.get("quick_hits") or []
    if len(quick_hits) < 4:
        problems.append(f"only {len(quick_hits)} quick_hits (need 4+)")

    stories = brief.get("stories") or []
    if len(stories) < MIN_PUBLISHABLE_STORIES:
        problems.append(f"only {len(stories)} stories (need {MIN_PUBLISHABLE_STORIES}+)")
    story_ids = set()
    for index, story in enumerate(stories):
        story_ids.add(str(story.get("id") or ""))
        for required in ("title", "url", "source", "summary"):
            if not str(story.get(required) or "").strip():
                problems.append(f"stories[{index}] missing {required}")
        url = str(story.get("url") or "")
        if url and not url.startswith("http"):
            problems.append(f"stories[{index}] has non-http url {url!r}")
        if "news.google.com" in url:
            problems.append(f"stories[{index}] url is an unresolved Google News redirect")

    sections = brief.get("sections") or []
    if len(sections) < 4:
        problems.append(f"only {len(sections)} sections (need 4+)")
    known_topics = set(TOPIC_PRIORITY)
    for index, section in enumerate(sections):
        topic = str(section.get("topic") or "")
        if topic not in known_topics:
            problems.append(f"sections[{index}] has unknown topic {topic!r}")
        section_story_ids = section.get("story_ids") or []
        if not section_story_ids:
            problems.append(f"sections[{index}] ({topic}) has no story_ids")
        for sid in section_story_ids:
            if str(sid) not in story_ids:
                problems.append(f"sections[{index}] references missing story {sid!r}")

    if not brief.get("hero_image_url"):
        problems.append("hero_image_url missing")
    image_count = sum(1 for story in stories if story.get("image_url"))
    if image_count < 3:
        problems.append(f"only {image_count} story images (want 3+)")

    scores = brief.get("sports_scores") or []
    for index, score in enumerate(scores):
        if not isinstance(score, dict):
            problems.append(f"sports_scores[{index}] is not an object")
            continue
        if not score.get("display"):
            problems.append(f"sports_scores[{index}] missing display")
        if not sports_mod.score_card_is_displayable(score):
            problems.append(
                f"sports_scores[{index}] ({score.get('id')}) is stale or expired"
            )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the published BriefSnap daily brief release payload"
    )
    parser.add_argument("--doc-id", help="Specific daily_briefs document id to check")
    parser.add_argument(
        "--brief-json",
        help="Audit a local daily brief JSON artifact instead of Firestore",
    )
    parser.add_argument("--max-age-hours", type=float, default=30)
    args = parser.parse_args()

    doc_id, brief = load_brief(args)
    problems = audit(doc_id, brief, args.max_age_hours)

    print(f"Audited daily brief {doc_id}")
    if problems:
        print(f"FAIL — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(
        f"OK — {len(brief.get('stories') or [])} stories, "
        f"{len(brief.get('sections') or [])} sections, "
        f"{len(brief.get('sports_scores') or [])} score cards, "
        f"model {brief.get('model_used')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
