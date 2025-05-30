"""Sports news summarizer using Gemini 2.5 Flash with Google Search."""

import os
from typing import Dict, List, Optional
from datetime import datetime
from google import genai
from google.genai import types


class SportsNewsSummarizer:
    """Class for generating sports news summaries using Gemini 2.5 Flash with Google Search."""
    
    def __init__(self):
        """Initialize the Gemini client."""
        self.client = genai.Client(
            api_key=os.environ.get("GEMINI_API_KEY"),
        )
        self.model = "gemini-2.5-flash-preview-05-20"
        
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
            
            prompt = f"""Please search for and summarize the latest news about {search_term} from the past 24 hours. 

Focus on:
- Breaking news and major developments
- Player trades, injuries, or signings
- Game results and upcoming important matchups
- League announcements or rule changes
- Coaching changes or front office moves

Provide a concise summary (2-3 sentences) of the most important developments, followed by 3-5 key bullet points of specific news items. Keep it informative but brief - total response should be under 200 words.

Format your response as:
**Summary:** [2-3 sentence overview]

**Key News:**
• [Key story 1]
• [Key story 2] 
• [Key story 3]
• [Additional stories if relevant]"""

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
    
    def generate_all_sports_summaries(self, sports_data: Dict[str, List[Dict]]) -> Dict[str, Dict]:
        """Generate news summaries for all sports that have upcoming games.
        
        Args:
            sports_data: Dictionary of sports games data by sport code
            
        Returns:
            Dictionary of summaries by sport code
        """
        summaries = {}
        
        print("\n====== Generating Sports News Summaries ======")
        
        for sport_code, games in sports_data.items():
            # Only generate summaries for sports that have games
            if not games:
                continue
                
            sport_name = self._get_sport_display_name(sport_code)
            print(f"Generating news summary for {sport_name}...")
            
            summary = self.generate_sport_summary(sport_code, sport_name)
            if summary:
                summaries[sport_code] = summary
                print(f"✅ Generated summary for {sport_name}")
            else:
                print(f"❌ Failed to generate summary for {sport_name}")
        
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