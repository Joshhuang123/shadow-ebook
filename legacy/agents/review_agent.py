"""
Review Agent - Manages spaced repetition and vocabulary review
"""
import json
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import random

import config.settings as settings


@dataclass
class ReviewItem:
    """Represents an item to review"""
    word: str
    ease_factor: float = 2.5  # SM-2 ease factor
    interval: int = 0  # Days until next review
    repetitions: int = 0  # Number of successful reviews
    next_review: str = ""  # ISO date string
    last_review: str = ""  # ISO date string
    notes: str = ""


class ReviewAgent:
    """Agent for managing spaced repetition review schedule"""

    def __init__(self):
        """Initialize review agent"""
        self.review_file = settings.WORDS_DIR / "review_schedule.json"
        self.review_items = self._load_review_items()

    def _load_review_items(self) -> Dict[str, ReviewItem]:
        """Load review schedule from file"""
        if self.review_file.exists():
            with open(self.review_file, 'r') as f:
                data = json.load(f)
                return {
                    word: ReviewItem(**item) for word, item in data.items()
                }
        return {}

    def _save_review_items(self):
        """Save review schedule to file"""
        data = {
            word: {
                "word": item.word,
                "ease_factor": item.ease_factor,
                "interval": item.interval,
                "repetitions": item.repetitions,
                "next_review": item.next_review,
                "last_review": item.last_review,
                "notes": item.notes
            }
            for word, item in self.review_items.items()
        }

        with open(self.review_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _calculate_interval(self,
                            item: ReviewItem,
                            quality: int) -> tuple:
        """
        Calculate next interval using SM-2 algorithm

        Args:
            item: Review item
            quality: Quality of recall (0-5)
                   5 - perfect response
                   4 - correct response after hesitation
                   3 - correct response with serious difficulty
                   2 - incorrect response; where correct one seemed easy to recall
                   1 - incorrect response; correct one remembered
                   0 - complete blackout

        Returns:
            Tuple of (new_ease_factor, new_interval, new_repetitions)
        """
        if quality < 3:
            # Failed - reset repetitions
            return item.ease_factor, 1, 0

        # Successful recall
        if item.repetitions == 0:
            interval = 1
        elif item.repetitions == 1:
            interval = 6
        else:
            interval = int(item.interval * item.ease_factor)

        # Update ease factor
        new_ease = item.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        new_ease = max(1.3, new_ease)  # Minimum ease factor

        return new_ease, interval, item.repetitions + 1

    def add_to_review(self, word: str, notes: str = ""):
        """
        Add a word to the review queue

        Args:
            word: Word to review
            notes: Optional notes
        """
        if word.lower() not in self.review_items:
            self.review_items[word.lower()] = ReviewItem(
                word=word,
                next_review=datetime.now().isoformat(),
                notes=notes
            )
            self._save_review_items()

    def review_word(self, word: str, quality: int) -> Dict:
        """
        Record a review result for a word

        Args:
            word: Word being reviewed
            quality: Quality of recall (0-5)

        Returns:
            Dict with updated review info
        """
        word_lower = word.lower()

        if word_lower not in self.review_items:
            return {"error": "Word not in review queue"}

        item = self.review_items[word_lower]
        ease, interval, reps = self._calculate_interval(item, quality)

        # Calculate next review date
        next_date = datetime.now() + timedelta(days=interval)

        # Update item
        item.ease_factor = ease
        item.interval = interval
        item.repetitions = reps
        item.next_review = next_date.isoformat()
        item.last_review = datetime.now().isoformat()

        self._save_review_items()

        return {
            "word": word,
            "quality": quality,
            "new_interval": interval,
            "next_review": next_date.strftime("%Y-%m-%d"),
            "ease_factor": round(ease, 2),
            "total_reviews": reps,
            "message": self._get_feedback(quality, interval)
        }

    def _get_feedback(self, quality: int, interval: int) -> str:
        """Get feedback message based on quality"""
        if quality >= 5:
            return f"Perfect! Next review in {interval} days"
        elif quality >= 4:
            return f"Good! Next review in {interval} days"
        elif quality >= 3:
            return f"Hesitation noted. Review in {interval} days"
        else:
            return "Needs more practice. Review tomorrow"

    def get_items_for_review(self, limit: int = 10) -> List[Dict]:
        """
        Get words due for review

        Args:
            limit: Maximum number of items

        Returns:
            List of dicts with word info
        """
        now = datetime.now()
        due_items = []

        for word, item in self.review_items.items():
            if item.next_review:
                next_date = datetime.fromisoformat(item.next_review)
                if next_date <= now:
                    due_items.append({
                        "word": item.word,
                        "interval": item.interval,
                        "repetitions": item.repetitions,
                        "ease_factor": round(item.ease_factor, 2),
                        "notes": item.notes
                    })

        # Sort by due date (oldest first)
        due_items.sort(key=lambda x: (
            self.review_items.get(x["word"].lower(), ReviewItem(x["word"])).interval,
            self.review_items.get(x["word"].lower(), ReviewItem(x["word"])).repetitions
        ))

        return due_items[:limit]

    def get_new_words(self, limit: int = 10) -> List[Dict]:
        """
        Get new words that haven't been reviewed yet

        Args:
            limit: Maximum number of items

        Returns:
            List of new words
        """
        new_words = [
            {
                "word": item.word,
                "notes": item.notes,
                "date_added": item.next_review[:10] if item.next_review else "unknown"
            }
            for word, item in self.review_items.items()
            if item.repetitions == 0
        ]

        return new_words[:limit]

    def get_statistics(self) -> Dict:
        """Get review statistics"""
        total = len(self.review_items)
        if total == 0:
            return {
                "total_words": 0,
                "due_today": 0,
                "learned": 0,
                "average_ease": 0
            }

        now = datetime.now()
        due_today = sum(
            1 for item in self.review_items.values()
            if item.next_review and
            datetime.fromisoformat(item.next_review) <= now
        )

        learned = sum(
            1 for item in self.review_items.values()
            if item.repetitions >= 3
        )

        avg_ease = sum(
            item.ease_factor for item in self.review_items.values()
        ) / total

        return {
            "total_words": total,
            "due_today": due_today,
            "learned": learned,
            "learning": total - learned,
            "average_ease": round(avg_ease, 2)
        }

    def clear_word(self, word: str):
        """Remove a word from review (e.g., if mastered)"""
        word_lower = word.lower()
        if word_lower in self.review_items:
            del self.review_items[word_lower]
            self._save_review_items()

    def reset_all(self):
        """Reset all review progress"""
        for word, item in self.review_items.items():
            item.repetitions = 0
            item.interval = 0
            item.ease_factor = 2.5
            item.next_review = datetime.now().isoformat()
        self._save_review_items()


if __name__ == "__main__":
    # Demo usage
    agent = ReviewAgent()

    # Add words
    agent.add_to_review("mitochondria", "powerhouse of the cell")
    agent.add_to_review("photosynthesis", "process in plants")
    agent.add_to_review("phenomenon", "plural: phenomena")

    # Simulate reviews
    print("Review Agent Demo")
    print("=" * 40)

    # Get stats
    stats = agent.get_statistics()
    print(f"\nStatistics:")
    print(f"  Total words: {stats['total_words']}")
    print(f"  Due today: {stats['due_today']}")
    print(f"  Learned: {stats['learned']}")

    # Get words for review
    new_words = agent.get_new_words()
    print(f"\nNew words to learn: {[w['word'] for w in new_words]}")
