"""Sports news summarizer using current Gemini models with Google Search."""

import os
from typing import Dict, List, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types

from newsaggregator.config.settings import SPORTS_NEWS_SUMMARY_CONCURRENCY


class SportsNewsSummarizer:
    """Class for generating sports news summaries using Gemini 3 Flash with Google Search."""
    
    def __init__(self):
        """Initialize the Gemini client."""
        self.client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
        )
        self.model = os.environ.get("BRIEFSNAP_SPORTS_GEMINI_MODEL", "gemini-3-flash-preview")
        
        # Sport mapping for search queries
        self.sports_mapping = {
            'nfl': 'NFL Football',
            'nba': 'NBA Basketball', 
            'mlb': 'MLB Baseball',
            'nhl': 'NHL Hockey',
            'ncaaf': 'College Football',
            'ncaab': 'College Basketball',
            'mls': 'MLS Soccer',
        }
    
    def generate_sport_summary(self, sport_code: str, sport_name: str) -> Optional[Dict]:
        """Generate a news summary for a specific sport.
        
        Args:
            sport_code: Sport code (e.g., 'nfl', 'nba')
            sport_name: Display name of the sport
            
        Returns:
            Dictionary with summary and key stories, or None if failed
        """
        try:
            search_term = self.sports_mapping.get(sport_code, sport_name)
            
            prompt = f"""Search for the most important {search_term} news from the past 24 hours.

BriefSnap sports copy must be accurate, source-aware, and sharply edited. Rank
stories by fan relevance, competitive impact, and confirmed sourcing. Ignore
rumors, betting filler, low-stakes injury trackers, generic previews, and
SEO roundup pages unless they contain a confirmed high-impact development.

Return under 150 words total:
Summary: one polished 20-35 word sentence.
Key News:
• 3-4 bullets, 12-18 words each, each with one concrete fact.

Use neutral wording. Do not mention Search, do not hedge with "reports say"
unless the underlying claim is not official, and do not include markdown
other than the two labels and bullets."""

            contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=prompt),
                    ],
                ),
            ]
            
            tools = [
                types.Tool(google_search=types.GoogleSearch()),
            ]
            
            generate_content_config = types.GenerateContentConfig(
                tools=tools,
                response_mime_type="text/plain",
                temperature=0.7,
            )

            # Generate content using streaming
            response_text = ""
            for chunk in self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                if chunk.text:
                    response_text += chunk.text

            if response_text.strip():
                return {
                    'sport_code': sport_code,
                    'sport_name': sport_name,
                    'summary': response_text.strip(),
                    'generated_at': datetime.now().isoformat(),
                    'model_used': self.model
                }
            else:
                print(f"No response generated for {sport_name}")
                return None
                
        except Exception as e:
            print(f"Error generating summary for {sport_name}: {e}")
            return None
    
    def generate_all_sports_summaries(
        self,
        sports_data: Dict[str, List[Dict]],
        sport_codes: Optional[List[str]] = None,
    ) -> Dict[str, Dict]:
        """Generate news summaries for all sports that have upcoming games.
        
        Args:
            sports_data: Dictionary of sports games data by sport code
            
        Returns:
            Dictionary of summaries by sport code
        """
        summaries = {}
        print("\n====== Generating Sports News Summaries ======")

        tasks = []
        selected_codes = sport_codes or [sport_code for sport_code, games in sports_data.items() if games]
        for sport_code in selected_codes:
            tasks.append((sport_code, self._get_sport_display_name(sport_code)))

        if not tasks:
            print("No sports with games available for summaries")
            return summaries

        worker_count = min(SPORTS_NEWS_SUMMARY_CONCURRENCY, len(tasks)) or 1

        if worker_count == 1:
            for sport_code, sport_name in tasks:
                print(f"Generating news summary for {sport_name}...")
                summary = self.generate_sport_summary(sport_code, sport_name)
                if summary:
                    summaries[sport_code] = summary
                    print(f"✅ Generated summary for {sport_name}")
                else:
                    print(f"❌ Failed to generate summary for {sport_name}")
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {
                    executor.submit(self.generate_sport_summary, sport_code, sport_name): (sport_code, sport_name)
                    for sport_code, sport_name in tasks
                }
                for future in as_completed(future_map):
                    sport_code, sport_name = future_map[future]
                    try:
                        summary = future.result()
                        if summary:
                            summaries[sport_code] = summary
                            print(f"✅ Generated summary for {sport_name}")
                        else:
                            print(f"❌ Failed to generate summary for {sport_name}")
                    except Exception as exc:
                        print(f"❌ Error generating summary for {sport_name}: {exc}")

        print(f"Generated {len(summaries)} sports news summaries")
        return summaries
    
    def _get_sport_display_name(self, sport_code: str) -> str:
        """Get display name for sport code.
        
        Args:
            sport_code: Sport code
            
        Returns:
            Display name for the sport
        """
        sport_names = {
            'nfl': 'NFL',
            'nba': 'NBA',
            'mlb': 'MLB',
            'nhl': 'NHL',
            'ncaaf': 'College Football',
            'ncaab': 'College Basketball',
            'mls': 'MLS',
        }
        return sport_names.get(sport_code, sport_code.upper()) 
