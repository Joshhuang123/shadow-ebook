"""
Scoring Agent - Evaluates pronunciation accuracy and fluency
Includes phoneme-level analysis using ARPAbet phoneme reference
"""
from typing import Dict, List, Tuple, Optional
from difflib import SequenceMatcher
import re
from dataclasses import dataclass

import numpy as np


# Phoneme reference database (ARPAbet)
# Based on CMU Pronouncing Dictionary
PHONEME_REFERENCE = {
    # Vowels
    'IY': {'ipa': 'iː', 'example': 'see', 'chinese': '长 /ee/ 音'},
    'EY': {'ipa': 'eɪ', 'example': 'say', 'chinese': '长 /ay/ 音'},
    'AY': {'ipa': 'aɪ', 'example': 'my', 'chinese': '长 /ai/ 音'},
    'OY': {'ipa': 'ɔɪ', 'example': 'boy', 'chinese': '长 /oy/ 音'},
    'AW': {'ipa': 'aʊ', 'example': 'how', 'chinese': '长 /aw/ 音'},
    'OW': {'ipa': 'oʊ', 'example': 'go', 'chinese': '长 /o/ 音'},
    'UW': {'ipa': 'uː', 'example': 'too', 'chinese': '长 /oo/ 音'},
    'UH': {'ipa': 'ʊ', 'example': 'put', 'chinese': '短 /oo/ 音'},
    'ER': {'ipa': 'ɜːr', 'example': 'bird', 'chinese': '卷舌 /er/ 音'},
    'AH': {'ipa': 'ʌ', 'example': 'but', 'chinese': '中央 /a/ 音'},
    'AA': {'ipa': 'ɑː', 'example': 'father', 'chinese': '开 /a/ 音'},
    'AE': {'ipa': 'æ', 'example': 'cat', 'chinese': '短 /a/ 音'},
    'AO': {'ipa': 'ɔː', 'example': 'law', 'chinese': '长 /aw/ 音'},
    'IH': {'ipa': 'ɪ', 'example': 'sit', 'chinese': '短 /i/ 音'},
    'EH': {'ipa': 'ɛ', 'example': 'bed', 'chinese': '短 /e/ 音'},
    # Consonants
    'K': {'ipa': 'k', 'example': 'kite', 'chinese': '清辅音 /k/'},
    'G': {'ipa': 'g', 'example': 'go', 'chinese': '浊辅音 /g/'},
    'P': {'ipa': 'p', 'example': 'pie', 'chinese': '清辅音 /p/'},
    'B': {'ipa': 'b', 'example': 'boy', 'chinese': '浊辅音 /b/'},
    'T': {'ipa': 't', 'example': 'tie', 'chinese': '清辅音 /t/'},
    'D': {'ipa': 'd', 'example': 'dog', 'chinese': '浊辅音 /d/'},
    'F': {'ipa': 'f', 'example': 'fun', 'chinese': '清辅音 /f/'},
    'V': {'ipa': 'v', 'example': 'very', 'chinese': '浊辅音 /v/'},
    'TH': {'ipa': 'θ', 'example': 'the', 'chinese': '咬舌清音 /th/'},
    'DH': {'ipa': 'ð', 'example': 'this', 'chinese': '咬舌浊音 /th/'},
    'S': {'ipa': 's', 'example': 'see', 'chinese': '清辅音 /s/'},
    'Z': {'ipa': 'z', 'example': 'zoo', 'chinese': '浊辅音 /z/'},
    'SH': {'ipa': 'ʃ', 'example': 'she', 'chinese': '清 /sh/ 音'},
    'ZH': {'ipa': 'ʒ', 'example': 'vision', 'chinese': '浊 /zh/ 音'},
    'HH': {'ipa': 'h', 'example': 'he', 'chinese': '送气音 /h/'},
    'CH': {'ipa': 'tʃ', 'example': 'cheese', 'chinese': '清 /ch/ 音'},
    'JH': {'ipa': 'dʒ', 'example': 'judge', 'chinese': '浊 /j/ 音'},
    'R': {'ipa': 'r', 'example': 'red', 'chinese': '卷舌 /r/ 音'},
    'L': {'ipa': 'l', 'example': 'love', 'chinese': '舌尖 /l/ 音'},
    'M': {'ipa': 'm', 'example': 'me', 'chinese': '双唇 /m/ 音'},
    'N': {'ipa': 'n', 'example': 'no', 'chinese': '舌尖 /n/ 音'},
    'NG': {'ipa': 'ŋ', 'example': 'sing', 'chinese': '舌根 /ng/ 音'},
    'W': {'ipa': 'w', 'example': 'we', 'chinese': '圆唇 /w/ 音'},
    'Y': {'ipa': 'j', 'example': 'yes', 'chinese': '半元音 /y/ 音'},
}


# Common words phoneme reference (for common words)
COMMON_WORD_PHONEMES = {
    'the': ['DH', 'AH0'],
    'a': ['AH0'],
    'an': ['AE', 'N'],
    'is': ['IH', 'Z'],
    'are': ['AA', 'R'],
    'was': ['W', 'AA', 'Z'],
    'were': ['W', 'ER', '0'],
    'have': ['HH', 'AE', 'V'],
    'has': ['HH', 'AE', 'Z'],
    'had': ['HH', 'AE', 'D'],
    'do': ['D', 'UW'],
    'does': ['D', 'AH', 'Z'],
    'did': ['D', 'IH', 'D'],
    'will': ['W', 'IH', 'L'],
    'would': ['W', 'UH', 'D'],
    'could': ['K', 'UH', 'D'],
    'should': ['SH', 'UH', 'D'],
    'can': ['K', 'AE', 'N'],
    'i': ['AY'],
    'me': ['M', 'IY'],
    'my': ['M', 'AY'],
    'you': ['Y', 'UW'],
    'your': ['Y', 'AO', 'R'],
    'he': ['HH', 'IY'],
    'she': ['SH', 'IY'],
    'it': ['IH', 'T'],
    'we': ['W', 'IY'],
    'they': ['DH', 'EY'],
    'them': ['DH', 'EH', 'M'],
    'this': ['DH', 'IH', 'S'],
    'that': ['DH', 'AE', 'T'],
    'these': ['DH', 'IY', 'Z'],
    'those': ['DH', 'OW', 'Z'],
    'here': ['HH', 'IY', 'R'],
    'there': ['DH', 'EH', 'R'],
    'where': ['W', 'EH', 'R'],
    'when': ['W', 'EH', 'N'],
    'what': ['W', 'AH', 'T'],
    'why': ['W', 'AY'],
    'how': ['HH', 'AW'],
    'and': ['AE', 'N', 'D'],
    'but': ['B', 'AH', 'T'],
    'or': ['AO', 'R'],
    'if': ['IH', 'F'],
    'because': ['B', 'IH', 'K', 'AO', 'Z'],
    'so': ['S', 'OW'],
    'very': ['V', 'EH', 'R', 'IY'],
    'just': ['JH', 'AH', 'S', 'T'],
    'will': ['W', 'IH', 'L'],
    'all': ['AO', 'L'],
    'also': ['AO', 'L', 'S', 'OW'],
    'know': ['N', 'OW'],
    'think': ['TH', 'IH', 'NG', 'K'],
    'see': ['S', 'IY'],
    'look': ['L', 'UH', 'K'],
    'come': ['K', 'AH', 'M'],
    'get': ['G', 'EH', 'T'],
    'give': ['G', 'IH', 'V'],
    'take': ['T', 'EY', 'K'],
    'say': ['S', 'EY'],
    'said': ['S', 'EH', 'D'],
    'tell': ['T', 'EH', 'L'],
    'told': ['T', 'OW', 'L', 'D'],
    'ask': ['AE', 'S', 'K'],
    'want': ['W', 'AO', 'N', 'T'],
    'need': ['N', 'IY', 'D'],
    'use': ['Y', 'UW', 'Z'],
    'find': ['F', 'AY', 'N', 'D'],
    'think': ['TH', 'IH', 'NG', 'K'],
    'make': ['M', 'EY', 'K'],
    'go': ['G', 'OW'],
    'went': ['W', 'EH', 'N', 'T'],
    'gone': ['G', 'AO', 'N'],
    'been': ['B', 'IH', 'N'],
    'being': ['B', 'IY', 'IH', 'NG'],
    'was': ['W', 'AA', 'Z'],
    'were': ['W', 'ER', '0'],
    'from': ['F', 'R', 'AH', 'M'],
    'with': ['W', 'IH', 'DH'],
    'about': ['AH', 'B', 'AW', 'T'],
    'into': ['IH', 'N', 'T', 'UW'],
    'over': ['OW', 'V', 'ER'],
    'after': ['AE', 'F', 'T', 'ER'],
    'before': ['B', 'IH', 'F', 'AO', 'R'],
    'between': ['B', 'IH', 'T', 'W', 'IY', 'N'],
    'through': ['TH', 'R', 'UW'],
    'during': ['D', 'UR', 'IH', 'NG'],
    'under': ['AH', 'N', 'D', 'ER'],
    'again': ['AH', 'G', 'EH', 'N'],
    'still': ['S', 'T', 'IH', 'L'],
    'even': ['IY', 'V', 'EH', 'N'],
    'only': ['OW', 'N', 'L', 'I'],
    'own': ['OW', 'N'],
    'same': ['S', 'EY', 'M'],
    'than': ['DH', 'AE', 'N'],
    'too': ['T', 'UW'],
    'much': ['M', 'AH', 'CH'],
    'many': ['M', 'EH', 'N', 'IY'],
    'most': ['M', 'OW', 'S', 'T'],
    'some': ['S', 'AH', 'M'],
    'such': ['S', 'AH', 'CH'],
    'no': ['N', 'OW'],
    'not': ['N', 'AO', 'T'],
    'only': ['OW', 'N', 'L', 'IY'],
    'just': ['JH', 'AH', 'S', 'T'],
    'than': ['DH', 'AE', 'N'],
    'creativity': ['K', 'R', 'IY', 'EY', 'T', 'IH', 'V', 'IH', 'T', 'IY'],
    'education': ['EH', 'JH', 'UH', 'K', 'EY', 'SH', 'AH', 'N'],
    'schools': ['S', 'K', 'UW', 'L', 'Z'],
    'kill': ['K', 'IH', 'L'],
    'creativity': ['K', 'R', 'IY', 'EY', 'T', 'IH', 'V', 'IH', 'T', 'IY'],
    'education': ['EH', 'JH', 'Y', 'UW', 'K', 'EY', 'SH', 'AH', 'N'],
    'people': ['P', 'IY', 'P', 'AH', 'L'],
    'children': ['CH', 'IH', 'L', 'D', 'R', 'EH', 'N'],
    'learning': ['L', 'ER', 'N', 'IH', 'NG'],
    'students': ['S', 'T', 'Y', 'UW', 'D', 'AH', 'N', 'T', 'S'],
    'world': ['W', 'ER', 'L', 'D'],
    'human': ['HH', 'Y', 'UW', 'M', 'AH', 'N'],
    'think': ['TH', 'IH', 'NG', 'K'],
    'different': ['D', 'IH', 'F', 'ER', 'AH', 'N', 'T'],
    'around': ['ER', 'AW', 'N', 'D'],
}


class ScoringAgent:
    """Agent for scoring user pronunciation"""

    def __init__(self):
        """Initialize scoring agent"""
        pass

    def calculate_similarity(self, reference: str, user: str) -> float:
        """
        Calculate text similarity between reference and user transcription

        Returns:
            Similarity score (0-100)
        """
        # Clean text
        ref_clean = self._clean_text(reference)
        user_clean = self._clean_text(user)

        # Use SequenceMatcher for similarity
        matcher = SequenceMatcher(None, ref_clean, user_clean)
        return matcher.ratio() * 100

    def _clean_text(self, text: str) -> str:
        """Clean text for comparison"""
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        return text.strip()

    def calculate_fluency(self, user_words: List[dict],
                          reference_duration: float = None) -> Dict:
        """
        Calculate fluency score based on speaking pace and pauses

        Args:
            user_words: List of dicts with 'word', 'start', 'end' from Whisper
            reference_duration: Expected duration in seconds

        Returns:
            Dict with fluency metrics
        """
        if not user_words:
            return {
                "wpm": 0,
                "pause_count": 0,
                "fluency_score": 0,
                "feedback": "No speech detected"
            }

        # Calculate WPM
        total_duration = user_words[-1]["end"] - user_words[0]["start"]
        word_count = len(user_words)
        wpm = (word_count / total_duration) * 60 if total_duration > 0 else 0

        # Count unnatural pauses (> 0.5 seconds between words)
        pause_count = 0
        pause_durations = []
        for i in range(1, len(user_words)):
            pause = user_words[i]["start"] - user_words[i-1]["end"]
            if pause > 0.5:
                pause_count += 1
                pause_durations.append(pause)

        # Calculate average pause duration
        avg_pause = np.mean(pause_durations) if pause_durations else 0

        # Fluency score (higher = more fluent)
        # Penalize for slow pace or too many pauses
        ideal_wpm = 150  # Target WPM for fluent English
        wpm_factor = 100 - abs(wpm - ideal_wpm) / ideal_wpm * 100
        wpm_factor = max(0, min(100, wpm_factor))

        pause_penalty = min(pause_count * 10, 30)  # Max 30 point penalty

        fluency_score = max(0, wpm_factor - pause_penalty)

        # Generate feedback
        if fluency_score >= 80:
            feedback = "Excellent fluency!"
        elif fluency_score >= 60:
            feedback = "Good pace, try to reduce pauses"
        elif fluency_score >= 40:
            feedback = "Slow down and practice word connections"
        else:
            feedback = "Focus on smooth delivery, avoid hesitations"

        return {
            "wpm": round(wpm, 1),
            "pause_count": pause_count,
            "avg_pause_duration": round(avg_pause, 2),
            "fluency_score": round(fluency_score, 1),
            "total_duration": round(total_duration, 2),
            "feedback": feedback
        }

    def calculate_pronunciation_score(self,
                                      reference: str,
                                      user_transcription: str,
                                      user_words: List[dict] = None) -> Dict:
        """
        Calculate overall pronunciation score

        Args:
            reference: Original sentence
            user_transcription: What Whisper understood from user
            user_words: Word-level timestamps (optional)

        Returns:
            Dict with detailed scoring
        """
        # 1. Text similarity (how close user said to reference)
        similarity = self.calculate_similarity(reference, user_transcription)

        # 2. Word-level accuracy
        ref_words = self._clean_text(reference).lower().split()
        user_words_clean = self._clean_text(user_transcription).lower().split()

        word_accuracy = self._calculate_word_accuracy(ref_words, user_words_clean)

        # 3. Fluency (if word timestamps available)
        fluency = self.calculate_fluency(user_words) if user_words else None

        # 4. Overall score (weighted average)
        # 60% similarity, 25% word accuracy, 15% fluency
        if fluency:
            overall = (similarity * 0.6 +
                      word_accuracy["accuracy"] * 0.25 +
                      fluency["fluency_score"] * 0.15)
        else:
            overall = (similarity * 0.7 + word_accuracy["accuracy"] * 0.3)

        # Determine level
        if overall >= 90:
            level = "🌟 Excellent"
        elif overall >= 75:
            level = "👍 Great"
        elif overall >= 60:
            level = "📚 Good"
        elif overall >= 40:
            level = "💪 Needs Practice"
        else:
            level = "📖 Keep Trying"

        # Identify problem words
        problem_words = []
        for w_acc in word_accuracy["words"]:
            if w_acc["accuracy"] < 70:
                word = w_acc["word"]
                suggestion = self._get_pronunciation_tip(word)
                problem_words.append({
                    "word": word,
                    "accuracy": w_acc["accuracy"],
                    "suggestion": suggestion
                })

        return {
            "overall_score": round(overall, 1),
            "level": level,
            "similarity": round(similarity, 1),
            "word_accuracy": word_accuracy,
            "fluency": fluency,
            "problem_words": problem_words,
            "reference": reference,
            "user_transcription": user_transcription
        }

    def _calculate_word_accuracy(self,
                                  ref_words: List[str],
                                  user_words: List[str]) -> Dict:
        """Calculate accuracy for each word"""
        # Use SequenceMatcher for word alignment
        matcher = SequenceMatcher(None, ref_words, user_words)
        matched_blocks = matcher.get_matching_blocks()

        words = []
        correct = 0
        total = len(ref_words)

        ref_idx = 0
        for block in matched_blocks:
            # Add non-matching reference words as errors
            while ref_idx < block[0]:
                words.append({
                    "word": ref_words[ref_idx],
                    "accuracy": 0,
                    "status": "missing"
                })
                ref_idx += 1

            # Add matching words
            for i in range(block.size):
                words.append({
                    "word": ref_words[ref_idx + i],
                    "accuracy": 100,
                    "status": "correct"
                })
                correct += 1

            ref_idx += block.size

        # Add remaining reference words
        while ref_idx < len(ref_words):
            words.append({
                "word": ref_words[ref_idx],
                "accuracy": 0,
                "status": "missing"
            })
            ref_idx += 1

        accuracy = (correct / total) * 100 if total > 0 else 0

        return {
            "accuracy": round(accuracy, 1),
            "words": words,
            "correct_count": correct,
            "total_words": total
        }

    def _get_pronunciation_tip(self, word: str) -> str:
        """Get pronunciation tip for a word using built-in phoneme reference"""
        word_lower = word.lower()

        # Check if word is in our reference
        if word_lower in COMMON_WORD_PHONEMES:
            phonemes = COMMON_WORD_PHONEMES[word_lower]
            tips = []
            for phone in phonemes:
                if phone in PHONEME_REFERENCE:
                    info = PHONEME_REFERENCE[phone]
                    tips.append(f"{phone}: {info['chinese']}")
            if tips:
                return " | ".join(tips)
            return f"Word: {word}"

        # Try to parse the word and guess phonemes based on spelling patterns
        tips = self._guess_phoneme_tips(word_lower)
        if tips:
            return " | ".join(tips)

        return f"Practice saying '{word}' slowly"

    def _guess_phoneme_tips(self, word: str) -> List[str]:
        """Guess phoneme tips based on spelling patterns"""
        tips = []
        word_lower = word.lower()

        # Common spelling patterns
        patterns = [
            ('th', ['TH', 'DH'], "咬舌音 'th'"),
            ('sh', ['SH'], "清 /sh/ 音"),
            ('ch', ['CH'], "清 /ch/ 音"),
            ('ck', ['K'], "清 /k/ 音"),
            ('ph', ['F'], "清 /f/ 音"),
            ('wr', ['R'], "卷舌 /r/ 音"),
            ('kn', ['N'], "开头 /n/ 音"),
            ('mb', ['M'], "结尾 /m/ 音"),
            ('ng', ['NG'], "舌根 /ng/ 音"),
            ('tion', ['SH', 'AH', 'N'], "tion 读 /shn/"),
            ('sion', ['ZH', 'AH', 'N'], "sion 读 /zhn/"),
            ('ous', ['AH', 'S'], "ous 读 /əs/"),
            ('ea', ['IY'], "ea 读 /ee/"),
            ('ee', ['IY'], "ee 读 /ee/"),
            ('oo', ['UW'], "oo 读 /oo/"),
            ('ou', ['AW'], "ou 读 /aw/"),
            ('ow', ['OW'], "ow 读 /ow/"),
            ('ai', ['EY'], "ai 读 /ay/"),
            ('ay', ['EY'], "ay 读 /ay/"),
            ('oi', ['OY'], "oi 读 /oy/"),
            ('oy', ['OY'], "oy 读 /oy/"),
            ('au', ['AO'], "au 读 /aw/"),
            ('aw', ['AO'], "aw 读 /aw/"),
            ('er', ['ER'], "er 卷舌音"),
            ('ir', ['ER'], "ir 卷舌音"),
            ('ur', ['ER'], "ur 卷舌音"),
        ]

        for pattern, phones, tip in patterns:
            if pattern in word_lower:
                tips.append(tip)

        return tips

    def get_word_phonemes(self, word: str) -> Dict:
        """
        Get phoneme information for a word

        Returns:
            Dict with phoneme details
        """
        word_lower = word.lower()

        if word_lower in COMMON_WORD_PHONEMES:
            phones = COMMON_WORD_PHONEMES[word_lower]
            return {
                "word": word,
                "phonemes": phones,
                "tips": self._get_phoneme_tips(phones),
                "source": "reference"
            }

        # Try to guess
        guessed = self._guess_phoneme_tips(word_lower)
        return {
            "word": word,
            "phonemes": [],
            "tips": guessed,
            "source": "guessed"
        }

    def _get_phoneme_tips(self, phones: List[str]) -> List[str]:
        """Get pronunciation tips for a list of phonemes"""
        tips = []

        for phone in phones:
            if phone in PHONEME_REFERENCE:
                info = PHONEME_REFERENCE[phone]
                tips.append(f"{phone}: {info['chinese']}")

        return tips

    def compare_phonemes(self, ref_word: str, user_word: str) -> Dict:
        """
        Compare phonemes between reference and user attempts

        Returns:
            Dict with phoneme-level comparison
        """
        ref_info = self.get_word_phonemes(ref_word)

        return {
            "reference": {
                "word": ref_word,
                "phonemes": ref_info.get("phonemes", []),
                "tips": ref_info.get("tips", [])
            },
            "user_attempt": {
                "word": user_word,
                "tips": self._get_pronunciation_tip(user_word)
            }
        }


if __name__ == "__main__":
    # Demo
    agent = ScoringAgent()

    # Test similarity
    ref = "I love watching movies"
    user = "I lav watching movirs"

    score = agent.calculate_pronunciation_score(ref, user)
    print("Pronunciation Score:")
    print(f"  Overall: {score['overall_score']}")
    print(f"  Level: {score['level']}")
    print(f"  Similarity: {score['similarity']}%")
    print(f"  Problem words: {score['problem_words']}")

    print("\nPhoneme Tips:")
    for word in ["creativity", "schools", "education"]:
        info = agent.get_word_phonemes(word)
        print(f"  {word}: {info.get('tips', [])}")
