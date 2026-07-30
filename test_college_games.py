"""Test script to verify college football games in Firestore."""

import os
import sys
from datetime import datetime

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from newsaggregator.storage.firebase_storage import FirebaseStorage

RUN_FIRESTORE_TESTS_ENV = "BRIEFSNAP_RUN_FIRESTORE_TESTS"


def test_college_games():
    """Query Firestore for college football games."""
    if os.environ.get(RUN_FIRESTORE_TESTS_ENV) != "1":
        pytest.skip(f"set {RUN_FIRESTORE_TESTS_ENV}=1 to run live Firestore sports checks")

    print("Connecting to Firestore...")
    db = FirebaseStorage.get_db()

    if not db:
        print("❌ Failed to connect to Firestore")
        return

    print("✅ Connected to Firestore\n")

    # Query for college football games
    print("Querying for college football games (sport_code='ncaaf')...")
    ncaaf_query = db.collection('sports_games').where('sport_code', '==', 'ncaaf').limit(5)
    ncaaf_docs = ncaaf_query.get(timeout=10)

    print(f"Found {len(ncaaf_docs)} NCAAF documents\n")

    current_time = datetime.now().timestamp()
    print(f"Current timestamp: {current_time} ({datetime.fromtimestamp(current_time)})\n")

    for doc in ncaaf_docs:
        data = doc.to_dict()
        print(f"Document ID: {doc.id}")
        print(f"  Sport: {data.get('sport')}")
        print(f"  Sport Code: {data.get('sport_code')}")
        print(f"  Status: {data.get('status')}")
        print(f"  Away: {data.get('away_team', {}).get('abbreviation')} @ Home: {data.get('home_team', {}).get('abbreviation')}")

        timestamp = data.get('timestamp')
        if timestamp:
            game_time = datetime.fromtimestamp(timestamp)
            print(f"  Timestamp: {timestamp} ({game_time})")
            print(f"  Future game: {timestamp > current_time}")
        else:
            print(f"  Timestamp: None")

        print(f"  Date: {data.get('date')}")
        print(f"  Formatted Date: {data.get('formatted_date')}")
        print(f"  Formatted Time: {data.get('formatted_time')}")
        print()

    # Also check for any 'cfb' sport code (old format)
    print("\nQuerying for old format college football games (sport_code='cfb')...")
    cfb_query = db.collection('sports_games').where('sport_code', '==', 'cfb').limit(5)
    cfb_docs = cfb_query.get(timeout=10)
    print(f"Found {len(cfb_docs)} CFB documents")

    if len(cfb_docs) > 0:
        print("⚠️  Found games with old 'cfb' sport code! These should be updated to 'ncaaf'")

    # Query for college basketball too
    print("\nQuerying for college basketball games (sport_code='ncaab')...")
    ncaab_query = db.collection('sports_games').where('sport_code', '==', 'ncaab').limit(5)
    ncaab_docs = ncaab_query.get(timeout=10)
    print(f"Found {len(ncaab_docs)} NCAAB documents\n")

if __name__ == '__main__':
    test_college_games()
