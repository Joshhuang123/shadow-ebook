"""
Owns: dynamic grammar practice question generation via LLM, with static-question fallback.
Does NOT own: static comprehension question bank (courses.py), practice progress persistence (parent_data.py),
              grammar topic content / explanations (grammarData in web/js/grammar.js).
"""
import json
import logging
import random
from flask import jsonify, request

from extensions.auth import _api_rate_limit_ok
from extensions.llm import get_llm_client

logger = logging.getLogger(__name__)


# === 语法 key → 提示用描述 (key 必须和 web/js/grammar.js 的 grammarQuestions dict 对得上) ===
GRAMMAR_KEY_DESCRIPTIONS = {
    # KET (A2)
    "ket-present-simple":      "一般现在时 (Present Simple) - 习惯性动作和客观事实,第三人称单数动词加 -s/-es",
    "ket-present-continuous":  "现在进行时 (Present Continuous) - be + V-ing,正在发生的动作",
    "ket-future-going-to":     "be going to 表将来计划 - 主语 + be going to + 动词原形",
    "ket-modals":              "情态动词 can/must/should - 表能力、义务、建议",
    "ket-comparatives":        "形容词比较级 - than / -er / more... than",
    "ket-frequency":           "频率副词和频率短语 - always/often/sometimes/never, once/twice a week",
    "ket-possessive":          "名词所有格 - 's / of / 形容词性物主代词",
    "ket-pronouns":            "人称代词和物主代词 - 主格/宾格/形容词性/名词性物主代词",
    "ket-prepositions":        "介词 in/on/at + 时间/地点 + 常用搭配 (next to, under, between)",
    "ket-imperative":          "祈使句 - 动词原形开头 / Don't + 动词原形",
    "ket-simple-past":         "一般过去时 (Simple Past) - 规则动词 -ed / 不规则动词",
    "ket-there-be":            "There be 句型 - There is/are + 名词,一般过去时 was/were",
    # PET (B1)
    "pet-present-perfect":     "现在完成时 (Present Perfect) - have/has + 过去分词,过去发生对现在有影响",
    "pet-past-perfect":        "过去完成时 (Past Perfect) - had + 过去分词,过去某动作之前",
    "pet-passive":             "被动语态 - be + 过去分词",
    "pet-conditional":         "条件句 - If + 一般现在时, will / If + 过去时, would",
    "pet-reported-speech":     "间接引语 - 时态后退、人称变化、say → tell",
    "pet-relatives":           "定语从句 - who/which/that/whose/where 引导",
    "pet-modals-perfect":      "情态动词完成时 - must have / can't have / should have / might have",
    "pet-used-to":             "used to + 动词原形 - 过去习惯",
    "pet-gerund-infinitive":   "动名词和不定式 - enjoy doing / want to do / decide to do",
    "pet-quantifiers":         "量词 - a few / a little / much / many / a lot of",
    "pet-adverb-clauses":      "状语从句 - because/although/while/when/so that",
    "pet-conjunctions":        "并列连词 - and/but/or/so, both...and/either...or/neither...nor",
}


# === LLM 输出 JSON schema ===
GRAMMAR_QUESTION_JSON_SCHEMA = {
    "type": "object",
    "required": ["q", "o", "a"],
    "additionalProperties": False,
    "properties": {
        "q": {
            "type": "string",
            "minLength": 8,
            "maxLength": 200,
            "description": "题干,用 ___ 表示填空位置。例:She ___ to school every day. (go)",
        },
        "o": {
            "type": "array",
            "minItems": 3,
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 50},
            "description": "3-4 个选项",
        },
        "a": {
            "type": "integer",
            "minimum": 0,
            "description": "正确选项在 o[] 里的索引,0-based",
        },
        "explanation": {
            "type": "string",
            "maxLength": 300,
            "description": "中文讲解,可选但强烈建议填",
        },
    },
}


# === 静态题库 fallback ===
# web/js/grammar.js 里的 grammarQuestions dict 复制一份(只 KET/PET 这些有题的 key)
# 孩子 key 来自前端,后端必须认得才能 fallback
STATIC_QUESTION_BANK: dict[str, list[dict]] = {
    "ket-present-simple": [
        {"q": "She ___ English every day. (like)", "o": ["like", "likes", "liking"], "a": 1},
        {"q": "When ___ you get up? (do)", "o": ["does", "do", "is"], "a": 1},
    ],
    "ket-present-continuous": [
        {"q": "What are you ___ now? (do)", "o": ["do", "doing", "does"], "a": 1},
        {"q": "Listen! The baby ___. (cry)", "o": ["cry", "cries", "is crying"], "a": 2},
    ],
    "ket-future-going-to": [
        {"q": "I ___ study English tomorrow.", "o": ["am going to", "going to", "go to"], "a": 0},
        {"q": "Look at the clouds! It ___ rain.", "o": ["is going to", "will", "can"], "a": 0},
    ],
    "ket-simple-past": [
        {"q": "I ___ to Beijing last year. (go)", "o": ["go", "went", "going"], "a": 1},
        {"q": "___ you ___ your homework yesterday?", "o": ["Did, do", "Do, did", "Does, do"], "a": 0},
    ],
    "ket-frequency": [
        {"q": "I go swimming ___ a week.", "o": ["twice", "two times", "second"], "a": 0},
        {"q": "___ do you exercise? - Every day.", "o": ["How often", "How many", "What time"], "a": 0},
    ],
    "ket-imperative": [
        {"q": "___ the door, please.", "o": ["Open", "Opens", "Opening"], "a": 0},
        {"q": "___ be late! It's impolite.", "o": ["Don't", "Not", "Doesn't"], "a": 0},
    ],
    "ket-possessive": [
        {"q": "That's ___ bag.", "o": ["Tom's", "Tom", "Toms"], "a": 0},
        {"q": "___ room is bigger, yours or mine?", "o": ["Whose", "Who's", "Who"], "a": 0},
    ],
    "ket-pronouns": [
        {"q": "Give the book to ___, please.", "o": ["me", "I", "my"], "a": 0},
        {"q": "This is ___ bag. It's not yours.", "o": ["hers", "her", "she"], "a": 0},
    ],
    "ket-prepositions": [
        {"q": "I was born ___ 2005.", "o": ["in", "on", "at"], "a": 0},
        {"q": "We have class ___ Monday.", "o": ["on", "in", "at"], "a": 0},
    ],
    "ket-comparatives": [
        {"q": "Tom is ___ than Jack.", "o": ["taller", "tallest", "more tall"], "a": 0},
        {"q": "She is the ___ girl in the class.", "o": ["tallest", "taller", "most tall"], "a": 0},
    ],
    "ket-modals": [
        {"q": "___ I open the window?", "o": ["Can", "Do", "Does"], "a": 0},
        {"q": "You ___ finish your homework first.", "o": ["must", "can", "may"], "a": 0},
    ],
    "ket-there-be": [
        {"q": "There ___ a book on the desk.", "o": ["is", "are", "have"], "a": 0},
        {"q": "There ___ many students in the classroom.", "o": ["are", "is", "has"], "a": 0},
    ],
    "pet-present-perfect": [
        {"q": "I ___ finished my homework.", "o": ["have", "has", "had"], "a": 0},
        {"q": "___ you ever ___ to Shanghai?", "o": ["Have, been", "Has, been", "Did, go"], "a": 0},
    ],
    "pet-past-perfect": [
        {"q": "By the time I arrived, she ___.", "o": ["had left", "left", "has left"], "a": 0},
        {"q": "He realized he ___ a mistake.", "o": ["had made", "made", "has made"], "a": 0},
    ],
    "pet-passive": [
        {"q": "English ___ in many countries.", "o": ["is spoken", "speaks", "spoken"], "a": 0},
        {"q": "The book ___ by J.K. Rowling.", "o": ["was written", "wrote", "is wrote"], "a": 0},
    ],
    "pet-conditional": [
        {"q": "If it ___ tomorrow, I will stay home.", "o": ["rains", "rained", "will rain"], "a": 0},
        {"q": "If I ___ a million dollars, I would buy a house.", "o": ["had", "have", "would have"], "a": 0},
    ],
    "pet-reported-speech": [
        {"q": '"I am tired," she said. She said she ___ tired.', "o": ["was", "is", "been"], "a": 0},
        {"q": '"I will come," he said. He said he ___.', "o": ["would come", "will come", "can come"], "a": 0},
    ],
    "pet-relatives": [
        {"q": "The girl ___ is singing is my sister.", "o": ["who", "which", "that"], "a": 0},
        {"q": "I have a friend ___ father is a doctor.", "o": ["whose", "who's", "whom"], "a": 0},
    ],
    "pet-modals-perfect": [
        {"q": "He ___ have been to Beijing. He knows so much about it.", "o": ["must", "can't", "shouldn't"], "a": 0},
        {"q": "She ___ have stolen the money. She was with me all day.", "o": ["can't", "must", "could"], "a": 0},
    ],
    "pet-used-to": [
        {"q": "I ___ play tennis, but now I play basketball.", "o": ["used to", "use to", "did use to"], "a": 0},
        {"q": "There ___ be a cinema here.", "o": ["used to", "use to", "used to"], "a": 0},
    ],
    "pet-gerund-infinitive": [
        {"q": "I enjoy ___ books.", "o": ["reading", "read", "to read"], "a": 0},
        {"q": "She decided ___ to Beijing.", "o": ["to move", "moving", "move"], "a": 0},
    ],
    "pet-quantifiers": [
        {"q": "There is ___ water in the glass.", "o": ["a little", "a few", "few"], "a": 0},
        {"q": "I have ___ friends in this city.", "o": ["a few", "a little", "few"], "a": 0},
    ],
    "pet-adverb-clauses": [
        {"q": "___ I was sleeping, someone called.", "o": ["While", "When", "After"], "a": 0},
        {"q": "I didn't go ___ I was sick.", "o": ["because", "although", "when"], "a": 0},
    ],
    "pet-conjunctions": [
        {"q": "I like tea ___ coffee.", "o": ["and", "but", "or"], "a": 0},
        {"q": "She's old ___ she's very active.", "o": ["but", "and", "so"], "a": 0},
    ],
}


# === LLM 出题 prompt ===
_GRAMMAR_QUESTION_PROMPT = """你是为 8-12 岁中国孩子出英语语法练习题的 AI 老师。

当前语法点:**{description}**

出题要求:
1. 题干用 ___ 表示填空位置;若需提示词,在括号里给动词原形。例:"She ___ to school every day. (go)"
2. 3-4 个选项,长度相近;**A(索引 0)必须是正确答案**,其余 2-3 个必须有合理干扰(语法错但常见错误模式)
3. 难度适合小学高年级到初一(KET/PET 水平)
4. 题目贴近孩子生活(学校、家庭、朋友、爱好)
5. explanation 用中文,一句话讲清为什么这个答案对、其他为什么错

{exclusion_block}

严格按下面的 JSON 格式返回,只输出 JSON,不要任何解释文字或 markdown code fence:

{{"q": "题干", "o": ["选项A", "选项B", "选项C"], "a": 0, "explanation": "中文讲解"}}"""


def _build_prompt(key: str, exclude_questions: list[str]) -> tuple[str, str]:
    """构造 system + user 两段消息。"""
    description = GRAMMAR_KEY_DESCRIPTIONS.get(key)
    if not description:
        return "", ""  # 未知 key,signal 给上层

    if exclude_questions:
        # 列出已出过的题避免重复
        exclusion_block = "不要出下面这些题(孩子已做过):\n" + "\n".join(f"- {q}" for q in exclude_questions[:20])
    else:
        exclusion_block = ""

    user = _GRAMMAR_QUESTION_PROMPT.format(
        description=description,
        exclusion_block=exclusion_block,
    )
    # system 保持空,所有指令都在 user 里更稳(Llama 系模型习惯)
    return "", user


def _try_static_fallback(key: str, exclude_questions: list[str]):
    """LLM 失败时从静态题库随机抽一道(避开已出的)。"""
    bank = STATIC_QUESTION_BANK.get(key, [])
    if not bank:
        return None
    available = [q for q in bank if q["q"] not in exclude_questions]
    if not available:
        available = bank  # 全做过了就循环
    return random.choice(available)


def register_routes(app):
    @app.route('/api/grammar/question/<key>')
    def get_grammar_question(key):
        """动态生成 1 道语法题。LLM 失败时降级到静态题库。

        Query params:
          exclude=  已经做过的题干列表(JSON 数组字符串),避免重复
        """
        if (resp := _rate_limited()):
            return resp

        if key not in GRAMMAR_KEY_DESCRIPTIONS:
            return jsonify({"success": False, "error": f"未知语法点: {key}"}), 404

        # 解析 exclude (JSON 数组字符串)
        exclude_raw = request.args.get("exclude", "[]")
        try:
            exclude_questions = json.loads(exclude_raw) if exclude_raw else []
            if not isinstance(exclude_questions, list):
                exclude_questions = []
        except json.JSONDecodeError:
            exclude_questions = []

        # 优先走 LLM
        system, user = _build_prompt(key, exclude_questions)
        if user:
            try:
                client = get_llm_client()
                obj = client.chat_json(
                    [{"role": "user", "content": user}],
                    schema=GRAMMAR_QUESTION_JSON_SCHEMA,
                )
                return jsonify({
                    "success": True,
                    "question": obj,
                    "source": "llm",
                })
            except Exception as e:
                logger.warning(f"LLM 出题失败,降级到静态题库: {type(e).__name__}: {e}")

        # LLM 失败 → 静态题库
        static_q = _try_static_fallback(key, exclude_questions)
        if static_q:
            return jsonify({
                "success": True,
                "question": static_q,
                "source": "static",
            })
        return jsonify({
            "success": False,
            "error": "LLM 不可用且静态题库为空",
            "retryable": True,
            "retry_after": 5,
        }), 503


def _rate_limited():
    ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'global')
    if not ok:
        return jsonify({
            "success": False,
            "error": f"请求过快, {retry} 秒后再试",
            "retryable": True,
            "retry_after": retry,
        }), 429
    return None