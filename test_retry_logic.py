#!/usr/bin/env python3
"""
Test script to verify the Gemini API retry logic and key switching.
This script tests the fixed retry decorator functionality.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from newsaggregator.fetchers.exa_fetcher import ExaFetcher
from newsaggregator.utils.retry import api_manager

def test_retry_logic():
    """Test the retry logic with article summary and key points generation."""
    print("=" * 80)
    print("TESTING GEMINI API RETRY LOGIC")
    print("=" * 80)

    # Check API keys
    print("\n1. Checking API Keys Configuration:")
    print(f"   - Number of API keys available: {len(api_manager.api_keys)}")
    print(f"   - Current key index: {api_manager.current_key_index + 1}")
    if len(api_manager.api_keys) > 1:
        print("   ✓ Multiple API keys configured for fallback")
    else:
        print("   ⚠ Only one API key configured - no fallback available")

    # Test article text
    test_article = """
    Breaking News: Major Scientific Discovery

    Scientists at MIT have announced a groundbreaking discovery in quantum computing
    that could revolutionize the field. The new quantum processor achieved unprecedented
    stability at room temperature, solving one of the major challenges in quantum computing.

    The research team, led by Dr. Jane Smith, demonstrated that their new approach using
    novel materials can maintain quantum coherence for up to 100 milliseconds at room
    temperature, a significant improvement over previous methods that required near-absolute
    zero temperatures.

    This breakthrough could accelerate the development of practical quantum computers and
    make them more accessible for widespread commercial use. Industry experts are calling
    it a potential game-changer for the technology sector.
    """

    # Initialize fetcher
    fetcher = ExaFetcher()

    # Test summary generation
    print("\n2. Testing Summary Generation:")
    print("   Generating summary for test article...")
    try:
        summary = fetcher._generate_summary(test_article)
        if summary:
            print(f"   ✓ Summary generated successfully:")
            print(f"     {summary}")
        else:
            print("   ✗ Summary generation returned empty string")
    except Exception as e:
        print(f"   ✗ Summary generation failed: {e}")

    # Test key points generation
    print("\n3. Testing Key Points Generation:")
    print("   Generating key points for test article...")
    try:
        key_points = fetcher._generate_key_points(test_article)
        if key_points:
            print(f"   ✓ Key points generated successfully:")
            for i, point in enumerate(key_points, 1):
                print(f"     {i}. {point}")
        else:
            print("   ✗ Key points generation returned empty list")
    except Exception as e:
        print(f"   ✗ Key points generation failed: {e}")

    # Report API key usage
    print("\n4. API Key Usage:")
    print(f"   - Final key index: {api_manager.current_key_index + 1}")
    if api_manager.key_rate_limited_until:
        print(f"   - Rate limited keys: {len(api_manager.key_rate_limited_until)}")
    else:
        print("   - No keys currently rate limited")

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    # Verify environment variables
    required_env_vars = ["GEMINI_API_KEY", "EXA_API_KEY"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]

    if missing_vars:
        print(f"ERROR: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these variables before running the test.")
        sys.exit(1)

    try:
        test_retry_logic()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
