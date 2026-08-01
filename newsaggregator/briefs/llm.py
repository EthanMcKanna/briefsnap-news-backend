"""OpenRouter chat-completions client for all pipeline LLM calls.

Every AI request in the backend goes through here so the provider/model
is configured in exactly one place (config.PRIMARY_MODEL et al).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

API_URL = "https://openrouter.ai/api/v1/chat/completions"

_HEADERS_STATIC = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://briefsnap.com",
    "X-Title": "BriefSnap",
}


class LLMError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not configured")
    return key


def _strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenRouter strict json_schema requires every object to declare
    additionalProperties: false and list all properties as required."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            node = dict(node)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
                node["properties"] = {k: walk(v) for k, v in node["properties"].items()}
            if "items" in node:
                node["items"] = walk(node["items"])
            return node
        return node

    return walk(schema)


def complete(
    messages: list[dict[str, str]],
    model: str,
    schema: dict[str, Any] | None = None,
    schema_name: str = "response",
    online: bool = False,
    max_tokens: int = 8192,
    temperature: float = 0.3,
    timeout: float | None = None,
    retries: int = 2,
) -> tuple[str, list[str]]:
    """Run one chat completion. Returns (content, citation_urls).

    `online=True` appends OpenRouter's web-search plugin variant so the
    model can ground on current web results (citations come back in
    message.annotations).
    """
    request_model = f"{model}:online" if online and ":" not in model else model
    body: dict[str, Any] = {
        "model": request_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": _strictify(schema),
            },
        }

    timeout = timeout or int(os.environ.get("BRIEFSNAP_LLM_TIMEOUT_MS", "120000")) / 1000
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(
                API_URL,
                headers={**_HEADERS_STATIC, "Authorization": f"Bearer {_api_key()}"},
                json=body,
                timeout=timeout,
            )
            if response.status_code == 429:
                raise LLMError(f"rate limited: {response.text[:200]}")
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise LLMError(str(payload["error"])[:300])
            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            if not content.strip():
                raise LLMError(f"empty completion (finish_reason={choice.get('finish_reason')})")
            citations = [
                annotation.get("url_citation", {}).get("url", "")
                for annotation in (message.get("annotations") or [])
                if annotation.get("type") == "url_citation"
            ]
            return content, [c for c in citations if c]
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(4 * attempt)
    raise LLMError(f"OpenRouter completion failed after {retries} attempts: {last_error}")


def complete_json(
    messages: list[dict[str, str]],
    model: str,
    schema: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    content, _ = complete(messages, model=model, schema=schema, **kwargs)
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("no JSON object in completion")
    return json.loads(cleaned[start : end + 1])
