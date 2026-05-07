#!/usr/bin/env python3
"""Primary production entry point for BriefSnap daily briefs."""

import os
import sys
import traceback

from newsaggregator.briefs.pipeline import main as run_daily_brief


def run_legacy_pipeline() -> int:
    """Keep the previous rotating aggregator available for manual fallback."""
    from datetime import datetime

    from newsaggregator.config.settings import DATA_DIR
    from newsaggregator.core.aggregator import NewsAggregator

    start_time = datetime.now()
    print(f"====== Legacy News Aggregator Started: {start_time} ======")
    os.makedirs(DATA_DIR, exist_ok=True)
    aggregator = NewsAggregator()
    aggregator.run()
    end_time = datetime.now()
    print(f"====== Legacy News Aggregator Completed: {end_time} ======")
    print(f"====== Total Duration: {end_time - start_time} ======")
    return 0


def main() -> int:
    try:
        if os.environ.get("BRIEFSNAP_LEGACY_PIPELINE", "").lower() == "true":
            return run_legacy_pipeline()
        return run_daily_brief(sys.argv[1:])
    except Exception as exc:
        print(f"ERROR: BriefSnap pipeline failed: {exc}")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
