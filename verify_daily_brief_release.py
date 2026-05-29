"""Release gate for the latest BriefSnap daily brief in Firestore.

This script checks the already-published app payload, then compares its sports
score packet with a fresh ESPN selector pass. It is intended to be run before an
iOS release or App Store upload.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from newsaggregator.briefs.pipeline import DailyBriefPipeline, PipelineOptions
from newsaggregator.fetchers.article_fetcher import ArticleFetcher


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
        return date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc)


def firebase_credential() -> credentials.Certificate:
    inline = os.environ.get("FIREBASE_CREDENTIALS")
    if inline:
        return credentials.Certificate(json.loads(inline))

    path = os.environ.get("FIREBASE_CREDENTIALS_PATH") or "firebase-credentials.json"
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Firebase credentials not found. Set FIREBASE_CREDENTIALS, "
            "FIREBASE_CREDENTIALS_PATH, or run from the backend repo."
        )
    return credentials.Certificate(path)


def latest_daily_brief(doc_id: str | None = None) -> tuple[str, dict[str, Any]]:
    if not firebase_admin._apps:
        firebase_admin.initialize_app(firebase_credential())

    db = firestore.client()
    if doc_id:
        snapshot = db.collection("daily_briefs").document(doc_id).get()
        if not snapshot.exists:
            raise RuntimeError(f"daily_briefs/{doc_id} does not exist")
        return snapshot.id, snapshot.to_dict() or {}

    docs = list(
        db.collection("daily_briefs")
        .order_by("generated_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    if not docs:
        raise RuntimeError("No daily_briefs documents found")
    return docs[0].id, docs[0].to_dict() or {}


def audit_daily_brief(
    brief: dict[str, Any],
    *,
    now: datetime,
    max_age: timedelta,
    max_sports_age: timedelta,
    max_final_score_age: timedelta,
    check_current_espn: bool,
) -> tuple[list[str], dict[str, Any]]:
    issues: list[str] = []
    stories = [story for story in brief.get("stories", []) if isinstance(story, dict)]
    scores = [score for score in brief.get("sports_scores", []) if isinstance(score, dict)]

    pipeline = DailyBriefPipeline(PipelineOptions(dry_run=True, publish=False))
    pipeline.sports_score_cards = scores
    issues.extend(pipeline._brief_quality_issues(brief))

    stored_quality_issues = brief.get("quality_issues")
    if stored_quality_issues:
        issues.append(f"published brief includes quality_issues: {stored_quality_issues}")

    generated_at = parse_datetime(brief.get("generated_at"))
    if generated_at is None:
        issues.append("generated_at is missing or invalid")
    elif now - generated_at > max_age:
        issues.append(f"brief is stale: generated {generated_at.isoformat()}")

    if str(brief.get("model_used") or "").lower() in {"dry-run", "source-ranked-fallback"}:
        issues.append(f"model_used is not a production generated run: {brief.get('model_used')}")

    if len(stories) < 6:
        issues.append(f"brief has too few visible stories: {len(stories)}")

    valid_image_count = sum(
        1
        for story in stories
        if ArticleFetcher._is_valid_image_url(str(story.get("image_url") or ""))
    )
    image_ratio = valid_image_count / len(stories) if stories else 0
    if stories and image_ratio < 0.75:
        issues.append(
            f"story image coverage is too low: {valid_image_count}/{len(stories)} valid images"
        )

    sports_story_count = sum(
        1
        for story in stories
        if DailyBriefPipeline._normalize_topic(story.get("topic")) == "SPORTS"
    )
    if scores and sports_story_count == 0:
        issues.append("sports scores are present without a sports news story")

    latest_verified_at = max(
        (date for date in (parse_datetime(score.get("verified_at")) for score in scores) if date),
        default=None,
    )
    if scores and latest_verified_at is None:
        issues.append("sports scores missing parseable verification timestamps")
    elif latest_verified_at and now - latest_verified_at > max_sports_age:
        issues.append(
            "sports scores are stale: latest verification "
            f"{latest_verified_at.isoformat()}"
        )

    non_displayable_scores = [
        str(score.get("id") or "<unknown>")
        for score in scores
        if not DailyBriefPipeline._score_card_is_displayable(score, now)
    ]
    if non_displayable_scores:
        issues.append(
            "sports scores include expired entries: " + ", ".join(non_displayable_scores)
        )

    current_score_ids: list[str] = []
    if check_current_espn:
        current_scores = pipeline._fetch_top_sports_scores()
        current_score_ids = [str(score.get("id") or "") for score in current_scores if score.get("id")]
        stored_score_ids = [str(score.get("id") or "") for score in scores if score.get("id")]
        if current_score_ids and stored_score_ids != current_score_ids:
            issues.append(
                "sports scores do not match fresh ESPN selector: "
                f"stored={stored_score_ids}, current={current_score_ids}"
            )
        if current_score_ids and not scores:
            issues.append("ESPN has displayable scores but the brief has none")

    stale_final_score_ids = stale_active_final_score_ids(now=now, max_age=max_final_score_age)
    if stale_final_score_ids:
        issues.append(
            "sports_games has active final scores older than "
            f"{max_final_score_age}: {', '.join(stale_final_score_ids)}"
        )

    coverage = brief.get("coverage_report") if isinstance(brief.get("coverage_report"), dict) else {}
    summary = {
        "story_count": len(stories),
        "valid_image_count": valid_image_count,
        "source_packet_count": coverage.get("source_packet_count", brief.get("source_count")),
        "source_packet_domains": coverage.get("source_packet_domains"),
        "leading_trusted_story_count": coverage.get("leading_trusted_story_count"),
        "max_leading_domain_count": coverage.get("max_leading_domain_count"),
        "visible_story_topics": sorted(
            (coverage.get("story_topic_counts") or {}).keys()
        ) if isinstance(coverage.get("story_topic_counts"), dict) else None,
        "sports_story_count": sports_story_count,
        "sports_score_count": len(scores),
        "latest_sports_verified_at": latest_verified_at.isoformat() if latest_verified_at else None,
        "current_espn_score_ids": current_score_ids,
        "stale_active_final_score_ids": stale_final_score_ids,
    }
    return issues, summary


def stale_active_final_score_ids(*, now: datetime, max_age: timedelta) -> list[str]:
    cutoff_ts = (now - max_age).timestamp()
    stale_ids: list[str] = []
    db = firestore.client()
    sport_codes = ("nfl", "ncaaf", "nba", "wnba", "ncaab", "mlb", "nhl", "mls")

    for sport_code in sport_codes:
        docs = (
            db.collection("sports_games")
            .where(filter=FieldFilter("sport_code", "==", sport_code))
            .where(filter=FieldFilter("timestamp", "<", cutoff_ts))
            .where(filter=FieldFilter("status", "==", "Final"))
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(20)
            .stream()
        )
        for doc in docs:
            stale_ids.append(doc.id)

    return stale_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the published BriefSnap daily brief release payload")
    parser.add_argument("--doc-id", help="Specific daily_briefs document id to check")
    parser.add_argument("--max-age-hours", type=float, default=30)
    parser.add_argument("--max-sports-age-minutes", type=float, default=20)
    parser.add_argument("--max-final-score-age-hours", type=float, default=6)
    parser.add_argument("--skip-current-espn", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now(timezone.utc)
    doc_id, brief = latest_daily_brief(args.doc_id)
    issues, summary = audit_daily_brief(
        brief,
        now=now,
        max_age=timedelta(hours=args.max_age_hours),
        max_sports_age=timedelta(minutes=args.max_sports_age_minutes),
        max_final_score_age=timedelta(hours=args.max_final_score_age_hours),
        check_current_espn=not args.skip_current_espn,
    )

    print(f"Checked daily_briefs/{doc_id} at {now.isoformat()}")
    for key, value in summary.items():
        print(f"{key}: {value}")

    if issues:
        print("\nRelease gate failed:")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("\nRelease gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
