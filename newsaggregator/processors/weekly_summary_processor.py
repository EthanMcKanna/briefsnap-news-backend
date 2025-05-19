"""Weekly summary processor that creates a summary of the week's top news."""

import time
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any

from newsaggregator.processors.gemini_processor import GeminiProcessor
from newsaggregator.storage.firebase_storage import FirebaseStorage

class WeeklySummaryProcessor:
    """Process weekly summaries from daily news summaries."""
    
    def __init__(self):
        """Initialize the weekly summary processor."""
        self.gemini_processor = GeminiProcessor()
        self.db = FirebaseStorage.initialize()
        self.weekly_summaries_dir = Path("data/weekly_summaries")
        
        # Create directory if it doesn't exist
        os.makedirs(self.weekly_summaries_dir, exist_ok=True)
    
    def get_week_timeframe(self) -> tuple:
        """Get the start and end timestamps for the past week.
        
        Returns:
            Tuple of (week_starting, week_ending) timestamps
        """
        # Use current time as the end of the week
        now = datetime.now(timezone.utc)
        # Week starts 7 days before
        week_start = now - timedelta(days=7)
        
        return week_start, now
    
    def retrieve_recent_summaries(self) -> Dict[str, List[Dict]]:
        """Retrieve summaries from the past week from Firestore.
        
        Returns:
            Dictionary of summaries by topic
        """
        if not self.db:
            print("Error: Firestore connection required for weekly summaries")
            return {}
            
        week_start, week_end = self.get_week_timeframe()
        return FirebaseStorage.get_summaries_in_timeframe(week_start, week_end)
    
    def generate_weekly_summary(self, topic: str, summaries: List[Dict]) -> Dict[str, Any]:
        """Generate a weekly summary for a specific topic.
        
        Args:
            topic: The news topic
            summaries: List of daily summaries for the topic
            
        Returns:
            Weekly summary data structure
        """
        # Prepare content from daily summaries
        content = self._prepare_content_for_gemini(summaries)
        
        # Get weekly summary from Gemini
        response = self.gemini_processor.generate_weekly_summary(content, topic)
        
        if not response:
            print(f"Failed to generate weekly summary for {topic}")
            return {}
            
        # Format the weekly summary document
        week_start, week_end = self.get_week_timeframe()
        
        return {
            "topic": topic,
            "created_at": datetime.now(timezone.utc),
            "week_starting": week_start,
            "week_ending": week_end,
            "weekly_summary": response.get("weekly_summary", ""),
            "key_developments": response.get("key_developments", []),
            "trending_topics": response.get("trending_topics", [])
        }
        
    def _prepare_content_for_gemini(self, summaries: List[Dict]) -> str:
        """Prepare a consolidated content string from summaries.
        
        Args:
            summaries: List of daily summaries
            
        Returns:
            Consolidated content string
        """
        content = []
        
        for summary in summaries:
            content.append(f"DATE: {summary.get('created_at', '')}")
            content.append(f"SUMMARY: {summary.get('Summary', '')}")
            
            if "Stories" in summary:
                content.append("TOP STORIES:")
                for i, story in enumerate(summary["Stories"], 1):
                    content.append(f"{i}. {story.get('title', '')}: {story.get('content', '')}")
            
            content.append("\n---\n")
            
        return "\n".join(content)
    
    def save_summary_to_file(self, topic: str, summary: Dict):
        """Save the weekly summary to a file.
        
        Args:
            topic: The news topic
            summary: Weekly summary data
            
        Returns:
            Path to the saved file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{topic.lower()}_weekly_{timestamp}.json"
        file_path = self.weekly_summaries_dir / filename
        
        try:
            # Convert datetime objects to strings for JSON serialization
            serializable_summary = {}
            for key, value in summary.items():
                if isinstance(value, datetime):
                    serializable_summary[key] = value.isoformat()
                else:
                    serializable_summary[key] = value
                    
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(serializable_summary, f, indent=2)
                
            print(f"Weekly summary saved to {file_path}")
            return file_path
            
        except Exception as e:
            print(f"Error saving weekly summary to file: {e}")
            return None
        
    def process_and_upload_weekly_summaries(self) -> Dict[str, Dict]:
        """Process weekly summaries for all topics and upload to Firestore.
        
        Returns:
            Dictionary of processed weekly summaries by topic
        """
        if not self.db:
            print("Error: Firestore connection required for weekly summaries")
            return {}
            
        # Get summaries from the past week
        recent_summaries = self.retrieve_recent_summaries()
        
        weekly_summaries = {}
        
        for topic, summaries in recent_summaries.items():
            print(f"Generating weekly summary for {topic}...")
            
            if not summaries:
                print(f"No recent summaries found for {topic}")
                continue
                
            # Generate weekly summary
            weekly_summary = self.generate_weekly_summary(topic, summaries)
            
            if weekly_summary:
                # Upload to Firestore
                FirebaseStorage.upload_weekly_summary(weekly_summary)
                
                # Save to file
                self.save_summary_to_file(topic, weekly_summary)
                
                weekly_summaries[topic] = weekly_summary
        
        return weekly_summaries 