"""Firestore publishing: daily brief, history, legacy shim, custom widgets."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from newsaggregator.config.settings import DATA_DIR

from .writer import generate_custom_widget

BRIEF_DIR = DATA_DIR / "daily_briefs"
MAX_CUSTOM_WIDGET_REQUESTS = 40


def firebase_credentials():
    from firebase_admin import credentials

    inline = os.environ.get("FIREBASE_CREDENTIALS")
    if inline:
        return credentials.Certificate(json.loads(inline))
    path = os.environ.get("FIREBASE_CREDENTIALS_PATH") or "firebase-credentials.json"
    if not Path(path).exists():
        raise RuntimeError(
            "Firebase credentials not found. Set FIREBASE_CREDENTIALS, "
            "FIREBASE_CREDENTIALS_PATH, or run from the backend repo."
        )
    return credentials.Certificate(path)


def _firestore_client():
    import firebase_admin
    from firebase_admin import firestore

    if not firebase_admin._apps:
        firebase_admin.initialize_app(firebase_credentials())
    return firestore.client()


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def write_artifact(brief: dict[str, Any]) -> Path:
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEF_DIR / f"daily_brief_{brief['id']}.json"
    path.write_text(json.dumps(brief, ensure_ascii=False, indent=2, default=str))
    print(f"Wrote artifact {path}")
    return path


def publish_firestore(brief: dict[str, Any]) -> None:
    db = _firestore_client()
    payload = dict(brief)
    payload["generated_at"] = parse_iso(payload["generated_at"])
    for story in payload.get("stories", []):
        if story.get("published_at"):
            try:
                story["published_at"] = parse_iso(story["published_at"])
            except (TypeError, ValueError):
                story["published_at"] = None
    for field in ("sports_scores_refreshed_at", "sports_scores_verified_at"):
        if payload.get(field):
            try:
                payload[field] = parse_iso(str(payload[field]))
            except (TypeError, ValueError):
                payload.pop(field, None)

    doc_id = payload["id"]
    db.collection("daily_briefs").document(doc_id).set(payload)
    db.collection("daily_brief_history").document(doc_id).set(payload)
    _publish_legacy_summary(db, payload)
    refresh_custom_widget_requests(db, payload)
    print(f"Published daily brief to Firestore document daily_briefs/{doc_id}")


def _publish_legacy_summary(db: Any, brief: dict[str, Any]) -> None:
    """Keep pre-V8 app builds alive with the old news_summaries shape."""
    stories = [
        {
            "id": story.get("id"),
            "StoryTitle": story.get("title"),
            "StoryDescription": story.get("summary"),
            "FullArticle": story.get("why_it_matters"),
            "Citations": [story.get("url")] if story.get("url") else [],
            "img_url": story.get("image_url"),
        }
        for story in brief.get("stories", [])[:10]
    ]
    legacy = {
        "topic": "TOP_NEWS",
        "summary": brief.get("summary", ""),
        "brief_summary": brief.get("dek") or brief.get("summary", ""),
        "bullet_points": brief.get("quick_hits", [])[:5],
        "timestamp": brief["generated_at"],
        "Stories": stories,
        "model_used": brief.get("model_used"),
    }
    db.collection("news_summaries").document(f"TOP_NEWS_{brief['id']}").set(legacy)


def refresh_custom_widget_requests(db: Any, brief: dict[str, Any]) -> None:
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter

        requests = list(
            db.collection("custom_widget_requests")
            .where(filter=FieldFilter("active", "==", True))
            .limit(MAX_CUSTOM_WIDGET_REQUESTS)
            .stream()
        )
    except Exception as exc:
        print(f"[WARN] Could not load custom widget requests: {exc}")
        return

    if not requests:
        print("No active custom widget requests to refresh")
        return

    context_stories = [
        {
            "title": story.get("title"),
            "source": story.get("source"),
            "summary": story.get("summary"),
        }
        for story in brief.get("stories", [])[:8]
    ]

    refreshed = 0
    for request_doc in requests:
        data = request_doc.to_dict() or {}
        prompt = str(data.get("prompt") or data.get("description") or "").strip()
        if len(prompt) < 4:
            continue
        now = datetime.now(timezone.utc)
        try:
            widget = generate_custom_widget(
                prompt=prompt,
                requested_title=str(data.get("title") or "").strip(),
                context_stories=context_stories,
            )
            request_doc.reference.set(
                {
                    "latest_widget": widget,
                    "latest_title": widget["title"],
                    "latest_summary": widget["summary"],
                    "latest_items": widget["items"],
                    "latest_generated_at": now,
                    "latest_model_used": widget["model_used"],
                    "status": "ready",
                    "error_message": None,
                    "updated_at": now,
                },
                merge=True,
            )
            db.collection("custom_widget_history").document(
                f"{request_doc.id}_{brief['id']}"
            ).set(
                {
                    "request_id": request_doc.id,
                    "device_id": data.get("device_id"),
                    "prompt": prompt,
                    "widget": widget,
                    "generated_at": now,
                }
            )
            refreshed += 1
        except Exception as exc:
            request_doc.reference.set(
                {
                    "status": "error",
                    "error_message": str(exc)[:500],
                    "updated_at": now,
                },
                merge=True,
            )
            print(f"[WARN] Custom widget {request_doc.id} failed: {exc}")

    print(f"Refreshed {refreshed} custom widget request(s)")


def refresh_latest_sports_scores(
    score_cards: list[dict[str, Any]], metadata: dict[str, Any]
) -> dict[str, Any]:
    """Merge a fresh score packet onto the newest published brief."""
    from firebase_admin import firestore

    db = _firestore_client()
    refreshed_at = datetime.now(timezone.utc)

    latest_docs = list(
        db.collection("daily_briefs")
        .order_by("generated_at", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )
    if not latest_docs:
        return {
            "success": False,
            "error": "No daily_briefs documents found",
            "scores_count": len(score_cards),
        }

    doc = latest_docs[0]
    update_payload: dict[str, Any] = {
        "sports_scores": score_cards,
        **metadata,
        "sports_scores_refreshed_at": refreshed_at,
        "sports_scores_source": "ESPN",
    }
    if update_payload.get("sports_scores_verified_at"):
        update_payload["sports_scores_verified_at"] = parse_iso(
            str(update_payload["sports_scores_verified_at"])
        )
    doc.reference.set(update_payload, merge=True)
    db.collection("daily_brief_history").document(doc.id).set(update_payload, merge=True)

    return {
        "success": True,
        "doc_id": doc.id,
        "scores_count": len(score_cards),
        "score_ids": [str(score.get("id") or "") for score in score_cards if score.get("id")],
        "refreshed_at": refreshed_at.isoformat(),
        "verified_at": metadata.get("sports_scores_verified_at"),
    }
