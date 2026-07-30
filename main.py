#!/usr/bin/env python3
"""Primary production entry point for BriefSnap daily briefs."""

import sys
import traceback

try:
    from dotenv import load_dotenv

    load_dotenv()  # local runs read .env; CI passes real env vars
except ImportError:
    pass

from newsaggregator.briefs.pipeline import main as run_daily_brief


def main() -> int:
    try:
        return run_daily_brief(sys.argv[1:])
    except Exception as exc:
        print(f"ERROR: BriefSnap pipeline failed: {exc}")
        print(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
