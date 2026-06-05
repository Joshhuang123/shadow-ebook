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
            # ==========================================
            # 新概念英语青少版2A 核心时态
            # ==========================================

            # Unit 1-2: 现在进行时 (Present Progressive)
            GrammarPoint(
                pattern=r'\b(am|is|are) \w+ing\b',
                explanation="【现在进行时】表示此刻或现阶段正在进行的动作。结构: be (am/is/are) + 动词-ing。口诀：主语+be+动词ing，表示正在做什么。",
                examples=[
                    "What are you doing? I'm waiting for you.",
                    "What is Robert doing? He is reading a book.",
                    "The children are playing in the garden."
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(am|is|are) (not )?\w+ing\b',
                explanation="【现在进行时否定句】be + not + 动词-ing。is not = isn't, are not = aren't, am not 通常缩写为 I'm not",
                examples=[
                    "I'm not watching TV. I'm doing my homework.",
                    "She isn't coming today. She is ill.",
                    "They aren't listening to me."
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(Am|Is|Are) \w+ \w+ing\?',
                explanation="【现在进行时一般疑问句】把 be 动词放到句首。Yes/No回答: Yes, 主语+be / No, 主语+be+not",
                examples=[
                    "Are you listening? Yes, I am. / No, I'm not.",
                    "Is she reading? Yes, she is. / No, she isn't.",
                    "What are they doing? They're playing football."
                ],
                level="beginner"
            ),

            # Unit 5-6, 10: 一般现在时 (Simple Present)
            GrammarPoint(
                pattern=r'\b(I|you|we|they) \w+(s|es)?\b',
                explanation="【一般现在时】表示经常性或习惯性的动作。主语是I/you/we/they时，动词用原形（第三人称单数要加-s/-es）",
                examples=[
                    "I usually get up at 7 o'clock.",
                    "You often go to school by bus.",
                    "They play football every weekend."
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(he|she|it) \w+s(es)?\b',
                explanation="【第三人称单数】he/she/it 后面的动词要加 -s 或 -es。这是 一般现在时 最容易出错的地方！口诀：他她它，做动作，动词后边加-s/-es。",
                examples=[
                    "She often goes to school by bike.",
                    "He usually gets up at 6:30.",
                    "It runs very fast. (它跑得很快)"
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(does|do|don\'t|doesn\'t)\b',
                explanation="【一般现在时否定句/疑问句】用 do/does 帮助构成否定和疑问。I/you/we/they → don't; he/she/it → doesn't。否定句：主语 + don't/doesn't + 动词原形",
                examples=[
                    "I don't like fish. (我不喜欢鱼)",
                    "She doesn't play tennis. (她不打网球)",
                    "Do you often read books? Yes, I do. / No, I don't."
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\bWhen do (you|we|they)\b|\bWhen does (he|she|it)\b',
                explanation="【时间询问】When 用来询问什么时候（时间点）。回答通常包含具体时间或频率。When do you usually get up? (你通常什么时候起床？)",
                examples=[
                    "When do you usually have breakfast? I have breakfast at 7:30.",
                    "When does she go to bed? She goes to bed at 9:30.",
                    "When do they play games? They play games on Saturday."
                ],
                level="beginner"
            ),

            # Unit 7: 频率副词
            GrammarPoint(
                pattern=r'\b(once|twice|three times)\b|\bHow often\b',
                explanation="【频率表达】once(一次), twice(两次), three times(三次), every day/week(每天/周)。How often...? 询问动作发生的频率。",
                examples=[
                    "How often do you go to the cinema? I go once a week.",
                    "She exercises twice a day.",
                    "We usually eat out once a month."
                ],
                level="beginner"
            ),

            # Unit 8: be going to 计划
            GrammarPoint(
                pattern=r'\b(am|is|are) going to\b',
                explanation="【be going to 表计划】表达未来的计划和打算。结构：be + going to + 动词原形。口诀：打算做某事，be going to 来帮你！",
                examples=[
                    "What are you going to do this weekend? I'm going to visit my grandmother.",
                    "She's going to buy a new dress.",
                    "We're going to have a party tomorrow."
                ],
                level="beginner"
            ),

            # Unit 9: want to do
            GrammarPoint(
                pattern=r'\bwant (to|you|him|her|them)\b',
                explanation="【want to do / want sb to do】want to do = 想要做某事；want sb to do = 想要某人做某事。want = 要，to = 去，do = 做。",
                examples=[
                    "What do you want to do? I want to play football.",
                    "I want you to help me with my English.",
                    "She wants to go to Beijing."
                ],
                level="beginner"
            ),

            # Unit 11-13: 一般过去时
            GrammarPoint(
                pattern=r'\b(was|were)\b',
                explanation="【一般过去时 - be动词】was 用于 I/he/she/it；were 用于 you/we/they。口诀：我(I)和他她它(he/she/it)，过去式用 was；你你们(you/we/they)，过去式用 were。",
                examples=[
                    "I was at home yesterday. (昨天我在家)",
                    "She was at school this morning. (今天早上她在学校)",
                    "They were very happy last night. (昨晚他们很开心)",
                    "Were you at school yesterday? Yes, I was. / No, I wasn't."
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b\w+(ed|ied)\b',
                explanation="【规则动词过去式】动词原形 + -ed（或特殊情况：辅音字母+y → y+ied）。常见变化：work → worked, play → played, study → studied, stop → stopped",
                examples=[
                    "I visited my grandmother yesterday. (昨天我去看望了奶奶)",
                    "She played tennis last weekend. (上周末她打了网球)",
                    "They walked to school this morning. (今天早上他们走路去学校)"
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\b(went|saw|ate|had|took|came|got|knew|bought|thought|found)\b',
                explanation="【不规则动词过去式】必须背！最常见的不规则动词：go→went, see→saw, eat→ate, have→had, take→took, come→came, get→got, know→knew, buy→bought, think→thought, find→found",
                examples=[
                    "I went to the park yesterday. (昨天我去了公园)",
                    "She saw a beautiful bird. (她看到一只美丽的鸟)",
                    "We had dinner at 7 last night. (昨晚7点我们吃了晚饭)"
                ],
                level="beginner"
            ),
            GrammarPoint(
                pattern=r'\bDid (I|you|we|they|he|she|it)\b|\b\w+ed\?',
                explanation="【一般过去时疑问句】用 Did 帮助构成：Did + 主语 + 动词原形？Yes, 主语+did. / No, 主语+didn't.",
                examples=[
                    "Did you go to school yesterday? Yes, I did. / No, I didn't.",
                    "Did she finish her homework? Yes, she did.",
                    "What did you do last weekend? I visited my grandparents."
                ],
                level="beginner"
            ),

            # Unit 3: 名词性物主代词
            GrammarPoint(
                pattern=r'\b(mine|yours|his|hers|ours|theirs)\b',
                explanation="【名词性物主代词】= my/your/his/her/its/our/their + 名词。口诀：名词性物主代词，后面不能加名词；单独使用，它就等于一个名词！例子：This book is mine. (= my book)",
                examples=[
                    "Whose is this book? It's mine. (这是我的书)",
                    "Is this your bag? No, it's hers. (这是她的)",
                    "These shoes are theirs. (这些鞋是他们的)"
                ],
                level="beginner"
            ),

            # Unit 4: 祈使句
            GrammarPoint(
                pattern=r'\b(Don\'t|Open|Close|Come|Go|Sit|Stand|Turn)\b',
                explanation="【祈使句】表示命令、请求或建议。肯定句：动词原形开头；否定句：Don't + 动词原形。Be careful! 祈使句省略主语(you)。",
                examples=[
                    "Open the door, please. (请开门)",
                    "Don't be late! (别迟到！)",
                    "Don't take your gloves off. (别脱下手套)"
                ],
                level="beginner"
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
