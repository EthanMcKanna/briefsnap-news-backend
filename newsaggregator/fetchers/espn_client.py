"""HTTP utilities for interacting with ESPN's public APIs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)


class ESPNApiError(RuntimeError):
    """Raised when an ESPN request fails permanently."""


@dataclass
class RequestMetrics:
    """Lightweight record of timing/attempt metadata."""

    url: str
    attempts: int
    elapsed: float
    status_code: Optional[int]


class ESPNHTTPClient:
    """Thin retrying HTTP JSON client for ESPN endpoints."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def get_json(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Request JSON with lightweight retry and error surfacing."""

        backoff = self.backoff_factor
        attempts = 0
        last_status = None
        start = time.monotonic()

        while attempts < max(self.max_retries, 1):
            attempts += 1
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=timeout or self.timeout,
                )
                last_status = response.status_code

                if response.status_code == 429 and attempts < self.max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:  # pragma: no cover - network
                if attempts >= self.max_retries:
                    elapsed = time.monotonic() - start
                    metrics = RequestMetrics(
                        url=url,
                        attempts=attempts,
                        elapsed=elapsed,
                        status_code=last_status,
                    )
                    raise ESPNApiError(f"ESPN request failed: {metrics}") from exc

                time.sleep(backoff)
                backoff = min(backoff * 2, 8)

        # Should never reach due to raise above, keep mypy satisfied
        raise ESPNApiError(f"ESPN request failed for {url}")
