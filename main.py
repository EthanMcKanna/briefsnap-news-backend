#!/usr/bin/env python3
"""Main entry point for the news aggregator system."""

import os
import sys
import traceback
from datetime import datetime
from newsaggregator.core.aggregator import NewsAggregator
from newsaggregator.config.settings import DATA_DIR

def main():
    """Main function to run the news aggregator."""
    start_time = datetime.now()
    print(f"====== News Aggregator Started: {start_time} ======")
    
    # Ensure data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    try:
        # Initialize and run the aggregator
        aggregator = NewsAggregator()
        aggregator.run()
        
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"====== News Aggregator Completed: {end_time} ======")
        print(f"====== Total Duration: {duration} ======")
        return 0
    except Exception as e:
        print(f"ERROR: News aggregator failed with exception: {str(e)}")
        print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main()) 