"""Compact validation gate for generated brief copy.

Roughly 25 crisp checks replace the V8 gate's 183 failure modes. Issues are
returned as human-readable strings that go straight back to the model as
corrective feedback.
"""

from __future__ import annotations

import re
from typing import Any

from .config import (
    BANNED_PHRASES,
    DANGLING_END_WORDS,
    DEK_WORDS,
    HEADLINE_WORDS,
    MIN_SECTIONS,
    QUICK_HITS_COUNT,
    QUICK_HIT_WORDS,
    STORY_SUMMARY_WORDS,
    STORY_TITLE_WORDS,
    SUMMARY_WORDS,
    WHY_IT_MATTERS_WORDS,
)


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", (text or "").strip()) if w]


def _ends_dangling(text: str) -> bool:
    words = _words(text)
    if not words:
        return True
    last = words[-1].strip(".,;:!?\"'").lower()
    return last in DANGLING_END_WORDS or text.rstrip().endswith(("…", "...", ",", ";", ":", "-", "—"))


def _check_range(
    issues: list[str], label: str, text: str, bounds: tuple[int, int]
) -> None:
    count = len(_words(text))
    low, high = bounds
    if count < low:
        issues.append(f'{label} is too short ({count} words, need {low}-{high}): "{text}"')
    elif count > high:
        issues.append(f'{label} is too long ({count} words, need {low}-{high})')


def _check_banned(issues: list[str], label: str, text: str) -> None:
    lowered = (text or "").lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            issues.append(f'{label} uses the banned phrase "{phrase}"')


def validate_brief(payload: dict[str, Any], packet: list[dict[str, Any]]) -> list[str]:
    """Return a list of issues; empty means publishable."""
    issues: list[str] = []
    packet_ids = {entry["id"] for entry in packet}
    packet_topics = {entry["topic"] for entry in packet}

    headline = str(payload.get("headline") or "")
    dek = str(payload.get("dek") or "")
    summary = str(payload.get("summary") or "")

    _check_range(issues, "headline", headline, HEADLINE_WORDS)
    if _ends_dangling(headline):
        issues.append(f'headline looks truncated — it ends on a connective word: "{headline}"')
    if headline.isupper():
        issues.append("headline must not be ALL CAPS")

    _check_range(issues, "dek", dek, DEK_WORDS)
    if dek.count(";") >= 2 or dek.lower().startswith(("lead stories", "top stories:")):
        issues.append("dek must be one written sentence, not a list of story titles")

    _check_range(issues, "summary", summary, SUMMARY_WORDS)
    for label, text in (("headline", headline), ("dek", dek), ("summary", summary)):
        _check_banned(issues, label, text)

    quick_hits = [str(hit) for hit in payload.get("quick_hits") or []]
    low, high = QUICK_HITS_COUNT
    if not (low <= len(quick_hits) <= high):
        issues.append(f"need {low}-{high} quick_hits, got {len(quick_hits)}")
    for index, hit in enumerate(quick_hits):
        count = len(_words(hit))
        if not (QUICK_HIT_WORDS[0] <= count <= QUICK_HIT_WORDS[1]):
            issues.append(
                f'quick_hits[{index}] must be {QUICK_HIT_WORDS[0]}-{QUICK_HIT_WORDS[1]} '
                f'words, got {count}: "{hit}"'
            )
        elif _ends_dangling(hit):
            issues.append(f'quick_hits[{index}] looks like a fragment: "{hit}"')
        _check_banned(issues, f"quick_hits[{index}]", hit)

    # Stories
    stories = payload.get("stories") or []
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    for index, story in enumerate(stories):
        story_id = str(story.get("id") or "")
        if story_id not in packet_ids:
            issues.append(f'stories[{index}] id "{story_id}" is not in the packet')
            continue
        if story_id in seen_ids:
            issues.append(f'stories[{index}] duplicates id "{story_id}"')
        seen_ids.add(story_id)

        title = str(story.get("title") or "")
        _check_range(issues, f"stories[{index}].title", title, STORY_TITLE_WORDS)
        title_key = title.lower()
        if title_key in seen_titles:
            issues.append(f'two stories share the title "{title}"')
        seen_titles.add(title_key)

        _check_range(
            issues, f"stories[{index}].summary", str(story.get("summary") or ""), STORY_SUMMARY_WORDS
        )
        why = str(story.get("why_it_matters") or "")
        _check_range(issues, f"stories[{index}].why_it_matters", why, WHY_IT_MATTERS_WORDS)
        story_summary = str(story.get("summary") or "")
        if why and story_summary and why.strip().lower() == story_summary.strip().lower():
            issues.append(f"stories[{index}].why_it_matters just restates the summary")
        if str(story.get("urgency") or "") not in ("high", "medium", "low"):
            issues.append(f"stories[{index}].urgency must be high, medium, or low")
        _check_banned(issues, f"stories[{index}].summary", story_summary)

    missing = packet_ids - seen_ids
    if missing:
        issues.append(
            f"stories must cover every packet id; missing {sorted(missing)[:6]}"
        )

    # Sections
    sections = payload.get("sections") or []
    section_topics = set()
    for index, section in enumerate(sections):
        topic = str(section.get("topic") or "")
        section_topics.add(topic)
        story_ids = [str(sid) for sid in section.get("story_ids") or []]
        if not story_ids:
            issues.append(f'sections[{index}] ("{topic}") has no story_ids')
        for sid in story_ids:
            if sid not in packet_ids:
                issues.append(f'sections[{index}] references unknown story id "{sid}"')
        if not str(section.get("summary") or "").strip():
            issues.append(f'sections[{index}] ("{topic}") needs a summary sentence')
        if not str(section.get("why_it_matters") or "").strip():
            issues.append(f'sections[{index}] ("{topic}") needs why_it_matters')

    uncovered_topics = packet_topics - section_topics
    if uncovered_topics:
        issues.append(f"every packet topic needs a section; missing {sorted(uncovered_topics)}")
    if len(sections) < min(MIN_SECTIONS, len(packet_topics)):
        issues.append(
            f"need at least {min(MIN_SECTIONS, len(packet_topics))} sections, got {len(sections)}"
        )

    return issues
