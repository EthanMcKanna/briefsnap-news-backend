"""Text similarity utilities for duplicate detection and text comparison."""

from difflib import SequenceMatcher
from datetime import datetime, timedelta

def clean_text_for_comparison(text):
    """Normalize text for better comparison.
    
    Args:
        text: Text to clean
        
    Returns:
        Cleaned text string
    """
    if not text:
        return ""
    # Convert to lowercase
    text = text.lower()
    # Remove special characters and extra whitespace
    text = ' '.join(text.split())
    # Remove common filler words
    filler_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
    return ' '.join(word for word in text.split() if word not in filler_words)

def calculate_similarity(text1, text2):
    """Calculate similarity ratio between two texts.
    
    Args:
        text1: First text string
        text2: Second text string
        
    Returns:
        Similarity ratio between 0 and 1
    """
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()

def is_same_day(date1, date2):
    """Check if two dates are on the same day.
    
    Args:
        date1: First datetime object
        date2: Second datetime object
        
    Returns:
        True if dates are on the same day, False otherwise
    """
    return (date1.year == date2.year and 
            date1.month == date2.month and 
            date1.day == date2.day) 