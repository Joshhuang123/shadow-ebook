"""
Grammar Agent - Analyzes and explains grammar structures
"""
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

import config.settings as settings


@dataclass
class GrammarPoint:
    """Represents a grammar point to learn"""
    pattern: str
    explanation: str
    examples: List[str]
    level: str  # beginner, intermediate, advanced


class GrammarAgent:
    """Agent for grammar analysis and explanation"""

    def __init__(self):
        """Initialize grammar agent"""
        self.grammar_notes = self._load_grammar_notes()
        self.grammar_patterns = self._build_patterns()

    def _load_grammar_notes(self) -> Dict:
        """Load grammar notes from JSON"""
        if settings.GRAMMAR_NOTES_FILE.exists():
            with open(settings.GRAMMAR_NOTES_FILE, 'r') as f:
                return json.load(f)
        return {
            "learned": {},  # pattern -> {explanation, examples, date_learned}
            "notes": []
        }

    def _save_grammar_notes(self):
        """Save grammar notes to JSON"""
        with open(settings.GRAMMAR_NOTES_FILE, 'w') as f:
            json.dump(self.grammar_notes, f, indent=2, ensure_ascii=False)

    def _build_patterns(self) -> List[GrammarPoint]:
        """Build list of common grammar patterns"""
        return [
            GrammarPoint(
                pattern=r'\bI am\b|\bI\'m\b',
                explanation="Present simple of 'to be' - describes current state",
                examples=["I am happy", "I'm tired"],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(I|you|we|they) (don\'t|do not|doesn\'t|do)\b',
                explanation="Negative form in present simple",
                examples=["I don't understand", "She doesn't know"],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(I|you|we|they) (will|shall)\b',
                explanation="Future tense - predictions or spontaneous decisions",
                examples=["I will help", "We shall see"],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\bgoing to\b',
                explanation="Future plans and intentions",
                examples=["I'm going to study", "She's going to travel"],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(I|he|she|it|we|they) (have|has|had)\b',
                explanation="Present perfect - past action with present relevance",
                examples=["I have finished", "She has gone"],
                level="intermediate"
            ),
            GrammarPoint(
                pattern=r'\b(I|he|she|it|we|they) (was|were)\b',
                explanation="Past simple of 'to be'",
                examples=["I was happy", "They were there"],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\bcould\b|\bwould\b|\bshould\b',
                explanation="Modal verbs - polite requests, possibility, advice",
                examples=["Could you help?", "You should try", "I would like"],
                level="intermediate"
            ),
            GrammarPoint(
                pattern=r'\bif\b.*\b(would|could|were)\b',
                explanation="Second conditional - hypothetical situations",
                examples=["If I were rich, I would travel", "If it rained, I would stay home"],
                level="intermediate"
            ),
            GrammarPoint(
                pattern=r'\b(I|he|she|it) (was|were) going to\b',
                explanation="Was/were going to - planned future that didn't happen",
                examples=["I was going to call", "She was going to come"],
                level="intermediate"
            ),
            GrammarPoint(
                pattern=r'\bnot only\b.*\bbut also\b',
                explanation="Emphatic conjunction - adding strong emphasis",
                examples=["Not only did she help, but also she stayed late"],
                level="advanced"
            ),
            GrammarPoint(
                pattern=r'\bwhatever\b|\bwhenever\b|\bwherever\b',
                explanation="-ever compounds -强调任何情况/时间/地点",
                examples=["Whatever you decide", "Whenever you're ready"],
                level="intermediate"
            ),
            GrammarPoint(
                pattern=r'\bthe more\b.*\bthe more\b',
                explanation="The more... the more - proportional relationship",
                examples=["The more you practice, the better you get"],
                level="advanced"
            ),
        ]

    def analyze_sentence(self, sentence: str) -> Dict:
        """
        Analyze a sentence for grammar points

        Args:
            sentence: Input sentence

        Returns:
            Dict with analysis results
        """
        sentence_lower = sentence.lower()

        # Find matching patterns
        matched_patterns = []
        for gp in self.grammar_patterns:
            if re.search(gp.pattern, sentence_lower, re.IGNORECASE):
                matched_patterns.append({
                    "pattern": gp.pattern,
                    "explanation": gp.explanation,
                    "examples": gp.examples,
                    "level": gp.level
                })

        # Identify sentence structure
        structure = self._analyze_structure(sentence)

        # Identify verb forms
        verb_forms = self._identify_verb_forms(sentence)

        return {
            "sentence": sentence,
            "grammar_points": matched_patterns,
            "structure": structure,
            "verb_forms": verb_forms,
            "difficulty": self._assess_difficulty(matched_patterns)
        }

    def _analyze_structure(self, sentence: str) -> Dict:
        """Analyze sentence structure"""
        words = sentence.split()

        # Basic structure detection
        structure_type = "simple"
        subject = ""
        verb = ""
        object_part = ""

        # Find subject (first noun/pronoun before verb)
        for i, word in enumerate(words):
            word_lower = word.lower().strip('.,!?')
            if word_lower in ['i', 'you', 'he', 'she', 'it', 'we', 'they', 'the', 'a', 'an']:
                # Likely start of sentence
                if i == 0 or words[i-1] in ['.', '!', '?', 'the', 'a', 'an']:
                    subject = word
                    # Look for verb after subject
                    for j in range(i+1, min(i+4, len(words))):
                        w = words[j].lower().strip('.,!?')
                        if w in ['am', 'is', 'are', 'was', 'were', 'have', 'has',
                                 'had', 'do', 'does', 'did', 'will', 'would',
                                 'can', 'could', 'should', 'might', 'must']:
                            verb = words[j]
                            object_part = ' '.join(words[j+1:]) if j+1 < len(words) else ""
                            structure_type = "sv" + ("o" if object_part else "")
                            break
                    break

        # Detect compound/complex
        if any(conj in sentence.lower() for conj in [' and ', ' but ', ' or ', ' because ', ' if ', ' when ', ' that ']):
            structure_type = "complex"

        return {
            "type": structure_type,
            "subject": subject,
            "verb": verb,
            "object": object_part,
            "word_count": len(words)
        }

    def _identify_verb_forms(self, sentence: str) -> List[str]:
        """Identify verb forms in sentence"""
        forms = []

        sentence_lower = sentence.lower()

        # Past simple: V2
        if re.search(r'\b(was|were|had|did|went|came|saw|ate|knew|got|gave|took)\b', sentence_lower):
            forms.append("Past Simple")

        # Present continuous: am/is/are + V-ing
        if re.search(r'\b(am|is|are) \w+ing\b', sentence_lower):
            forms.append("Present Continuous")

        # Past continuous: was/were + V-ing
        if re.search(r'\b(was|were) \w+ing\b', sentence_lower):
            forms.append("Past Continuous")

        # Present perfect: have/has + V3
        if re.search(r'\b(have|has) \w+ed\b|\b(have|has) gone|been|done\b', sentence_lower):
            forms.append("Present Perfect")

        # Past perfect: had + V3
        if re.search(r'\bhad \w+ed\b|\bhad gone|been|done\b', sentence_lower):
            forms.append("Past Perfect")

        # Future: will/shall/going to
        if re.search(r'\b(will|shall|going to)\b', sentence_lower):
            forms.append("Future")

        # Passive: be + V3
        if re.search(r'\b(is|are|was|were|been) \w+ed\b', sentence_lower):
            forms.append("Passive Voice")

        return forms

    def _assess_difficulty(self, patterns: List) -> str:
        """Assess difficulty based on matched patterns"""
        if not patterns:
            return "basic"

        # Handle both GrammarPoint objects and dicts
        levels = []
        for p in patterns:
            if isinstance(p, dict):
                levels.append(p.get('level', 'beginner'))
            else:
                levels.append(p.level)

        if "advanced" in levels:
            return "advanced"
        elif "intermediate" in levels:
            return "intermediate"
        else:
            return "beginner"

    def explain_grammar_point(self, pattern_type: str) -> Dict:
        """
        Get explanation for a grammar point type

        Args:
            pattern_type: Type of grammar point (e.g., 'past_simple', 'present_perfect')

        Returns:
            Dict with explanation and examples
        """
        # Build a lookup dictionary
        explanations = {
            "past_simple": {
                "name": "Past Simple",
                "explanation": "Used for completed actions in the past. "
                              "For regular verbs: add -ed. For irregular verbs: memorize the V2 form.",
                "usage": ["Point in past", "Series of past actions", "Past habits"],
                "examples": ["I walked to school", "She went to work", "They played football"],
                "time_expressions": ["yesterday", "last week", "ago", "in 2020"]
            },
            "present_continuous": {
                "name": "Present Continuous",
                "explanation": "Used for actions happening NOW. Structure: am/is/are + verb-ing",
                "usage": ["Actions happening now", "Temporary situations", "Changing situations"],
                "examples": ["I am reading", "She is working", "They are learning"],
                "time_expressions": ["now", "right now", "currently", "at the moment"]
            },
            "present_perfect": {
                "name": "Present Perfect",
                "explanation": "Used for past actions with present relevance. "
                              "Structure: have/has + past participle (V3).",
                "usage": ["Life experience", "Recent actions with present effect", "Unfinished time periods"],
                "examples": ["I have seen that movie", "She has finished her work"],
                "time_expressions": ["ever", "never", "just", "already", "yet", "today", "this week"]
            },
            "future": {
                "name": "Future Tense (will/going to)",
                "explanation": "Will: predictions, spontaneous decisions. "
                              "Going to: plans, intentions, evidence-based predictions.",
                "usage": ["Predictions", "Plans", "Promises", "Decisions at speak time"],
                "examples": ["I will help you", "I'm going to study tonight"],
                "time_expressions": ["tomorrow", "next week", "soon", "in the future"]
            }
        }

        return explanations.get(pattern_type.lower(), {
            "name": pattern_type,
            "explanation": "Review this grammar point in your textbook or dictionary.",
            "usage": [],
            "examples": [],
            "time_expressions": []
        })

    def add_grammar_note(self, pattern: str, explanation: str, example: str):
        """Add a personal grammar note"""
        if pattern not in self.grammar_notes["learned"]:
            self.grammar_notes["learned"][pattern] = {
                "explanation": explanation,
                "examples": [example],
                "date_added": datetime.now().isoformat()
            }
        elif example not in self.grammar_notes["learned"][pattern]["examples"]:
            self.grammar_notes["learned"][pattern]["examples"].append(example)

        self._save_grammar_notes()

    def get_grammar_notes(self) -> Dict:
        """Get all personal grammar notes"""
        return self.grammar_notes["learned"]


if __name__ == "__main__":
    # Demo usage
    agent = GrammarAgent()

    # Test sentence analysis
    sentences = [
        "I was going to call you yesterday.",
        "If I were rich, I would buy a yacht.",
        "Not only did she win, but she also broke the record."
    ]

    for sentence in sentences:
        print(f"\n📝 Analyzing: {sentence}")
        result = agent.analyze_sentence(sentence)
        print(f"  Structure: {result['structure']['type']}")
        print(f"  Verb forms: {result['verb_forms']}")
        print(f"  Difficulty: {result['difficulty']}")
        if result['grammar_points']:
            for gp in result['grammar_points']:
                print(f"  📚 {gp.explanation}")
