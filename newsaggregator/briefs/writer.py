"""LLM writing layer.

The stories are already chosen when this module runs. Gemini receives a
curated packet and only writes copy — headline, dek, summary, quick hits,
section framing, and per-story summaries — under a strict JSON schema.
Validation failures are fed back verbatim for one corrective rewrite before
falling back to the next model. No post-hoc regex repair.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from google import genai

from .config import (
    BANNED_PHRASES,
    FALLBACK_MODEL,
    GEMINI_TIMEOUT_MS,
    PRIMARY_MODEL,
    TOPIC_NAMES,
    WIDGET_MODEL,
)
from .enrich import excerpt
from .models import Cluster

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "dek": {"type": "string"},
        "summary": {"type": "string"},
        "quick_hits": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "story_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["topic", "title", "summary", "why_it_matters", "story_ids"],
            },
        },
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["id", "title", "summary", "why_it_matters", "urgency"],
            },
        },
    },
    "required": ["headline", "dek", "summary", "quick_hits", "sections", "stories"],
}

CUSTOM_WIDGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "items"],
}


class WriterError(RuntimeError):
    pass


def _gemini_keys() -> list[str]:
    return [
        key
        for key in (os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_API_KEY_2"))
        if key
    ]


def _client(key: str) -> genai.Client:
    return genai.Client(api_key=key, http_options={"timeout": GEMINI_TIMEOUT_MS})


def _parse_json(text: str | None) -> dict[str, Any]:
    if not text:
        raise WriterError("empty model response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise WriterError("no JSON object in model response")
    return json.loads(cleaned[start : end + 1])


def build_packet(clusters: list[Cluster]) -> list[dict[str, Any]]:
    packet = []
    for cluster in clusters:
        lead = cluster.lead
        packet.append(
            {
                "id": cluster.id,
                "topic": cluster.topic,
                "headline": lead.title,
                "outlets": cluster.sources[:6],
                "outlet_count": len(cluster.domains),
                "published_at": lead.published_at.isoformat() if lead.published_at else None,
                "excerpt": excerpt(cluster),
            }
        )
    return packet


def _brief_prompt(packet: list[dict[str, Any]], feedback: list[str] | None) -> str:
    topics_present = sorted(
        {entry["topic"] for entry in packet},
        key=lambda code: list(TOPIC_NAMES).index(code) if code in TOPIC_NAMES else 99,
    )
    section_names = ", ".join(f"{code} ({TOPIC_NAMES.get(code, code)})" for code in topics_present)
    feedback_block = ""
    if feedback:
        joined = "\n".join(f"- {issue}" for issue in feedback)
        feedback_block = (
            "\n\nYour previous draft failed review. Fix every issue below and "
            f"return the corrected JSON:\n{joined}\n"
        )

    return f"""You are the writer for BriefSnap, a morning news brief that respects the reader's time.

The day's stories have already been selected and verified. Your only job is to write clear, information-dense copy. Do not add, drop, or merge stories.

STORY PACKET (JSON):
{json.dumps(packet, ensure_ascii=False, indent=1)}

Write JSON with exactly these fields:

1. "headline" — the single most consequential story from the packet, restated in plain language. 6-12 words. A complete thought in sentence case. Never cut off mid-phrase.
2. "dek" — ONE flowing sentence, 14-28 words, that frames what kind of news day this is. Written prose. Never a list of story titles.
3. "summary" — 3-4 sentences, 55-100 words, connecting the day's most important threads across topics. Specific facts, not vibes.
4. "quick_hits" — 5-6 items. Each is a complete standalone statement of 8-18 words covering a DIFFERENT packet story. Include the key number or name. No fragments.
5. "sections" — one per topic present: {section_names}. Each has "topic" (the code), "title" (2-4 plain words), "summary" (one sentence on what happened in this lane), "why_it_matters" (one sentence, the consequence), and "story_ids" listing every packet id of that topic.
6. "stories" — one entry for EVERY packet id, keeping packet order. Each has:
   - "id" — copied exactly from the packet.
   - "title" — the story headline, cleaned up: sentence case, no publisher name, no trailing site suffix, 4-14 words.
   - "summary" — one sentence, 16-30 words, the concrete facts: who did what, key numbers, where.
   - "why_it_matters" — one sentence, 8-22 words, the consequence or stake. Never restate the summary.
   - "urgency" — "high" only for genuinely urgent breaking developments, else "medium" or "low".

STYLE RULES:
- Ground every claim in the packet excerpts. Never invent facts, numbers, or outcomes.
- Plain confident language. No hype, no hedging.
- Banned phrases: {", ".join(BANNED_PHRASES)}.
- Never end a headline or quick hit with a preposition, article, or conjunction.
- No markdown, no emoji, no ALL CAPS.{feedback_block}"""


def write_brief(
    clusters: list[Cluster],
    validate: Any,
    model_override: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Generate brief copy. Returns (payload, model_used).

    `validate` is a callable(payload, packet) -> list[str] of issues.
    Flow per model: draft -> validate -> one corrective rewrite with the
    issues -> validate. Then the next model. Then raise.
    """
    packet = build_packet(clusters)
    keys = _gemini_keys()
    if not keys:
        raise WriterError("GEMINI_API_KEY is not configured")

    models = [model_override] if model_override else [PRIMARY_MODEL, FALLBACK_MODEL]
    last_error: Exception | None = None
    last_issues: list[str] = []

    for key_index, key in enumerate(keys, start=1):
        client = _client(key)
        for model in models:
            feedback: list[str] | None = None
            for attempt in (1, 2):
                label = f"{model} via key-{key_index} (attempt {attempt})"
                try:
                    print(f"Writing brief with {label}")
                    config: dict[str, Any] = {
                        "response_mime_type": "application/json",
                        "response_json_schema": BRIEF_SCHEMA,
                        # Thinking tokens share this budget on gemini-3 models,
                        # so leave generous headroom for the ~20-story JSON.
                        "max_output_tokens": 32768,
                        "temperature": 0.3,
                    }
                    if model.startswith("gemini-3"):
                        config["thinking_config"] = {"thinking_level": "low"}
                    response = client.models.generate_content(
                        model=model,
                        contents=_brief_prompt(packet, feedback),
                        config=config,
                    )
                    payload = _parse_json(response.text)
                except Exception as exc:
                    last_error = exc
                    print(f"[WARN] {label} failed: {exc}")
                    if _is_auth_error(exc):
                        break  # try next key
                    time.sleep(2)
                    continue

                issues = validate(payload, packet)
                if not issues:
                    return payload, model
                last_issues = issues
                print(f"[WARN] {label} failed review: {issues[:6]}")
                feedback = issues
            else:
                continue
            break  # auth error: skip remaining models on this key

    detail = f"; last issues: {last_issues[:6]}" if last_issues else f"; last error: {last_error}"
    raise WriterError(f"All models failed to produce a publishable brief{detail}")


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc)
    return "API_KEY_INVALID" in text or "PERMISSION_DENIED" in text or "API key not valid" in text


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------


def generate_custom_widget(
    prompt: str,
    requested_title: str,
    context_stories: list[dict[str, Any]],
) -> dict[str, Any]:
    """One user widget. Search grounding is used here because widget topics
    routinely fall outside the curated packet."""
    keys = _gemini_keys()
    if not keys:
        raise WriterError("GEMINI_API_KEY is not configured")

    widget_prompt = f"""Create one BriefSnap custom news widget for a user-defined topic.

User request:
{prompt}

Today's brief context (for tone, not content):
{json.dumps(context_stories, ensure_ascii=False)}

Rules:
- Use Google Search for current facts about the user's topic.
- Return JSON with "title" (max 5 words), "summary" (one sentence, max 24 words), and "items" (3-5 bullets, max 12 words each).
- Every item is a current, concrete fact. No filler, no markdown, no meta-commentary.
- If the request is broad, pick the most newsworthy current angle.

Preferred title, if useful: {requested_title or "none"}"""

    configs = (
        # Search-grounded first; if search quota is exhausted, degrade to a
        # schema-only call rather than failing the widget outright.
        (WIDGET_MODEL, {"tools": [{"google_search": {}}], "response_mime_type": "application/json",
                        "response_json_schema": CUSTOM_WIDGET_SCHEMA, "max_output_tokens": 4096,
                        "temperature": 0.25}),
        (WIDGET_MODEL, {"response_mime_type": "application/json",
                        "response_json_schema": CUSTOM_WIDGET_SCHEMA, "max_output_tokens": 4096,
                        "temperature": 0.25}),
        (FALLBACK_MODEL, {"response_mime_type": "application/json",
                          "response_json_schema": CUSTOM_WIDGET_SCHEMA, "max_output_tokens": 4096,
                          "temperature": 0.25}),
    )

    last_error: Exception | None = None
    for key in keys:
        client = _client(key)
        for model, config in configs:
            try:
                response = client.models.generate_content(
                    model=model, contents=widget_prompt, config=config
                )
                payload = _parse_json(response.text)
                title = " ".join(str(payload.get("title") or requested_title or prompt).split()[:5])
                summary = str(payload.get("summary") or "").strip()
                items = [
                    " ".join(str(item).split()[:14]).rstrip(".")
                    for item in (payload.get("items") or [])
                    if str(item).strip()
                ][:5]
                if not summary and not items:
                    raise WriterError("empty widget")
                return {
                    "topic": "CUSTOM",
                    "title": title[:80],
                    "summary": summary[:280],
                    "items": items,
                    "prompt": prompt,
                    "model_used": model,
                }
            except Exception as exc:
                last_error = exc
                if _is_auth_error(exc):
                    break
                if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
                    time.sleep(10)
    raise WriterError(f"Custom widget generation failed: {last_error}")
