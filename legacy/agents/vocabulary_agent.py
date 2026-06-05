"""
Vocabulary Agent - Extracts, tracks, and manages vocabulary learning
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Set, Optional
from datetime import datetime
from collections import defaultdict

import config.settings as settings


class VocabularyAgent:
    """Agent for vocabulary extraction and management"""

    def __init__(self):
        """Initialize vocabulary agent"""
        self.known_words = self._load_known_words()
        self.unknown_words = self._load_unknown_words()

    def _load_known_words(self) -> Set[str]:
        """Load known words from file"""
        if settings.KNOWN_WORDS_FILE.exists():
            with open(settings.KNOWN_WORDS_FILE, 'r') as f:
                return set(line.strip().lower() for line in f if line.strip())
        return set()

    def _load_unknown_words(self) -> Dict:
        """Load unknown words tracking from JSON"""
        if settings.UNKNOWN_WORDS_FILE.exists():
            with open(settings.UNKNOWN_WORDS_FILE, 'r') as f:
                return json.load(f)
        return {}

    def _save_unknown_words(self):
        """Save unknown words to JSON"""
        with open(settings.UNKNOWN_WORDS_FILE, 'w') as f:
            json.dump(self.unknown_words, f, indent=2, ensure_ascii=False)

    def extract_words(self, text: str) -> List[str]:
        """
        Extract individual words from text

        Args:
            text: Input text

        Returns:
            List of cleaned words
        """
        # Remove punctuation and split
        words = text.lower().split()
        cleaned = []

        for word in words:
            # Remove leading/trailing punctuation
            cleaned_word = word.strip('.,!?;:()[]{}""\'\'-')
            if cleaned_word:
                cleaned.append(cleaned_word)

        return cleaned

    def identify_unknown_words(self, text: str) -> Dict:
        """
        Identify words that are likely unknown to the learner

        Args:
            text: Input text (e.g., sentence from movie)

        Returns:
            Dict with unknown word information
        """
        words = self.extract_words(text)

        unknown_info = {}
        for word in words:
            word_lower = word.lower()

            # Skip if already known
            if word_lower in self.known_words:
                continue

            # Check if already tracked
            if word_lower in self.unknown_words:
                # Increment practice count
                self.unknown_words[word_lower]["times_encountered"] += 1
                self.unknown_words[word_lower]["last_encountered"] = datetime.now().isoformat()
            else:
                # Add new unknown word
                self.unknown_words[word_lower] = {
                    "word": word,
                    "first_encountered": datetime.now().isoformat(),
                    "last_encountered": datetime.now().isoformat(),
                    "times_encountered": 1,
                    "times_practiced": 0,
                    "mastery_level": 0,  # 0-100, increases with practice
                    "contexts": [],  # Sentences where encountered
                    "notes": ""
                }

        self._save_unknown_words()

        # Return only newly discovered words
        return {
            word: info for word, info in self.unknown_words.items()
            if info["times_encountered"] == 1
        }

    def mark_as_known(self, word: str):
        """
        Mark a word as known and remove from unknown list

        Args:
            word: Word to mark as known
        """
        word_lower = word.lower()

        # Add to known words
        self.known_words.add(word_lower)

        # Save known words
        with open(settings.KNOWN_WORDS_FILE, 'a') as f:
            f.write(f"{word_lower}\n")

        # Remove from unknown words
        if word_lower in self.unknown_words:
            del self.unknown_words[word_lower]
            self._save_unknown_words()

    def practice_word(self, word: str, score: float):
        """
        Record a practice session for a word

        Args:
            word: Word practiced
            score: Score from pronunciation practice (0-100)
        """
        word_lower = word.lower()

        if word_lower in self.unknown_words:
            self.unknown_words[word_lower]["times_practiced"] += 1

            # Update mastery level (weighted average)
            old_mastery = self.unknown_words[word_lower]["mastery_level"]
            practices = self.unknown_words[word_lower]["times_practiced"]
            new_mastery = (old_mastery * (practices - 1) + score) / practices

            self.unknown_words[word_lower]["mastery_level"] = min(100, new_mastery)
            self._save_unknown_words()

    def get_words_for_review(self, limit: int = 10) -> List[Dict]:
        """
        Get words that need review (low mastery, not practiced recently)

        Args:
            limit: Maximum number of words to return

        Returns:
            List of word dicts sorted by mastery level and recency
        """
        words = [
            {
                "word": word,
                **info
            }
            for word, info in self.unknown_words.items()
        ]

        # Sort by mastery level (lowest first) then by last encountered
        words.sort(key=lambda x: (x["mastery_level"], x["last_encountered"]))

        return words[:limit]

    def get_word_details(self, word: str) -> Optional[Dict]:
        """Get details about a specific word"""
        return self.unknown_words.get(word.lower())

    def export_words(self, format: str = "json") -> str:
        """
        Export all unknown words

        Args:
            format: 'json', 'csv', or 'txt'

        Returns:
            Exported data as string
        """
        if format == "json":
            return json.dumps(self.unknown_words, indent=2, ensure_ascii=False)

        elif format == "csv":
            lines = ["word,first_encountered,times_encountered,times_practiced,mastery_level"]
            for word, info in sorted(self.unknown_words.items()):
                lines.append(
                    f"{word},{info['first_encountered']},"
                    f"{info['times_encountered']},{info['times_practiced']},"
                    f"{info['mastery_level']:.1f}"
                )
            return "\n".join(lines)

        elif format == "txt":
            return "\n".join(sorted(self.unknown_words.keys()))

        return ""

    def get_statistics(self) -> Dict:
        """Get vocabulary learning statistics"""
        total_unknown = len(self.unknown_words)
        total_known = len(self.known_words)
        total_encountered = total_unknown + total_known

        # Calculate average mastery
        if self.unknown_words:
            avg_mastery = sum(
                info["mastery_level"] for info in self.unknown_words.values()
            ) / total_unknown
        else:
            avg_mastery = 100

        # Words by mastery range
        mastery_buckets = {
            "learning": 0,  # 0-30%
            "practicing": 0,  # 30-70%
            "familiar": 0,  # 70-90%
            "mastered": 0  # 90-100%
        }

        for info in self.unknown_words.values():
            level = info["mastery_level"]
            if level >= 90:
                mastery_buckets["mastered"] += 1
            elif level >= 70:
                mastery_buckets["familiar"] += 1
            elif level >= 30:
                mastery_buckets["practicing"] += 1
            else:
                mastery_buckets["learning"] += 1

        return {
            "total_unknown_words": total_unknown,
            "total_known_words": total_known,
            "total_words_encountered": total_encountered,
            "average_mastery": round(avg_mastery, 1),
            "mastery_distribution": mastery_buckets
        }


if __name__ == "__main__":
    # Demo usage
    agent = VocabularyAgent()

    # Test extracting words
    sentence = "The mitochondria is the powerhouse of the cell."
    words = agent.extract_words(sentence)
    print(f"Extracted words: {words}")

    # Identify unknown words
    unknown = agent.identify_unknown_words(sentence)
    print(f"Unknown words: {list(unknown.keys())}")

    # Statistics
    stats = agent.get_statistics()
    print(f"\nVocabulary Statistics:")
    print(f"  Unknown: {stats['total_unknown_words']}")
    print(f"  Known: {stats['total_known_words']}")
    print(f"  Avg mastery: {stats['average_mastery']}%")
