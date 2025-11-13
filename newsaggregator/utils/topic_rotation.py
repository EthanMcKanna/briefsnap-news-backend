"""Persistent topic rotation to spread article selection across the day."""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class TopicRotationManager:
    """Tracks the last-processed time for each topic and persists it to disk."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._state: Dict[str, float] = self._load_state()

    def _load_state(self) -> Dict[str, float]:
        try:
            with open(self.state_file, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
                return {topic: float(ts) for topic, ts in data.items()}
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as handle:
                json.dump(self._state, handle, indent=2)
        except Exception:
            pass

    def get_next_batch(
        self,
        available_topics: List[str],
        max_topics: Optional[int],
        cooldown_seconds: int,
    ) -> List[str]:
        if not available_topics:
            return []

        max_count = max_topics or len(available_topics)
        now = time.time()

        eligible: List[Tuple[float, str]] = []

        for topic in available_topics:
            last_ts = self._state.get(topic, 0.0)
            entry = (last_ts, topic)
            if not last_ts or now - last_ts >= cooldown_seconds:
                eligible.append(entry)

        eligible.sort(key=lambda item: item[0])

        if eligible:
            return [topic for _, topic in eligible[:max_count]]

        # No topics have cleared cooldown yet
        return []

    def mark_processed(self, topics: List[str]) -> None:
        if not topics:
            return

        timestamp = time.time()
        for topic in topics:
            self._state[topic] = timestamp
        self._save_state()
