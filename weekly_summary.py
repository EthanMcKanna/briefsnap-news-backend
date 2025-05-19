#!/usr/bin/env python3
"""Run the weekly summary generation process."""

import time
from datetime import datetime
import signal
import sys

from newsaggregator.processors.weekly_summary_processor import WeeklySummaryProcessor

def signal_handler(signum, frame):
    """Handle graceful shutdown on SIGINT/SIGTERM."""
    print("\nShutdown signal received. Exiting...")
    sys.exit(0)

def main():
    """Run the weekly summary generation process."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        start_time = time.time()
        print(f"Starting weekly summary generation at {datetime.now()}")
        
        # Initialize and run the weekly summary processor
        processor = WeeklySummaryProcessor()
        weekly_summaries = processor.process_and_upload_weekly_summaries()
        
        # Log results
        summary_count = sum(1 for summaries in weekly_summaries.values() for _ in summaries) \
            if isinstance(weekly_summaries, dict) else 0
        
        print(f"Generated {summary_count} weekly summaries")
        print(f"Process completed in {time.time() - start_time:.2f} seconds")
        
    except Exception as e:
        print(f"Error during weekly summary generation: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 