"""
Owns: built-in course content (新概念英语青少版 2A) + comprehension question bank.
Does NOT own: TTS for course sentences (tts.py), student progress on courses (parent_data.py).
"""
import random
from flask import jsonify


# === 课程内容 (按单元组织的核心句子) ===
COURSE_CONTENT = {
    "name": "新概念英语青少版2A",
    "units": [
        {
            "name": "Unit 1-2: 现在进行时",
            "sentences": [
                {"text": "What are you doing?", "translation": "你在做什么？", "grammar": "现在进行时 be + doing"},
                {"text": "I'm waiting for you.", "translation": "我在等你。", "grammar": "主语+be+动词ing"},
                {"text": "What is Robert doing?", "translation": "Robert在做什么？", "grammar": "现在进行时疑问句"},
                {"text": "He is reading a book.", "translation": "他在读书。", "grammar": "现在进行时"},
                {"text": "The children are playing in the garden.", "translation": "孩子们正在花园里玩。", "grammar": "现在进行时复数"},
                {"text": "Are you listening to me?", "translation": "你在听我说话吗？", "grammar": "现在进行时一般疑问句"},
                {"text": "Yes, I am. / No, I'm not.", "translation": "是的，我在听。/ 不，我没在听。", "grammar": "肯定/否定回答"},
            ]
        },
        {
            "name": "Unit 5-6: 一般现在时",
            "sentences": [
                {"text": "I usually get up at seven o'clock.", "translation": "我通常七点起床。", "grammar": "一般现在时 习惯性动作"},
                {"text": "When do you usually have breakfast?", "translation": "你通常什么时候吃早饭？", "grammar": "When提问 时间"},
                {"text": "I usually have breakfast at half past seven.", "translation": "我通常七点半吃早饭。", "grammar": "时间表达"},
                {"text": "She often goes to school by bike.", "translation": "她经常骑自行车去学校。", "grammar": "第三人称单数 goes"},
                {"text": "He usually gets up early.", "translation": "他通常早起。", "grammar": "第三人称单数 gets"},
                {"text": "Do you often read English books?", "translation": "你经常读英语书吗？", "grammar": "一般现在时疑问句"},
                {"text": "Yes, I do. / No, I don't.", "translation": "是的，我经常读。/ 不，我不经常读。", "grammar": "简略回答"},
            ]
        },
        {
            "name": "Unit 7: 频率",
            "sentences": [
                {"text": "How often do you go to the cinema?", "translation": "你多久去看一次电影？", "grammar": "频率提问 How often"},
                {"text": "I go to the cinema once a week.", "translation": "我每周去看一次电影。", "grammar": "once a week 频率"},
                {"text": "She exercises twice a day.", "translation": "她每天锻炼两次。", "grammar": "twice频率"},
                {"text": "We usually eat out once a month.", "translation": "我们通常每月出去吃一次饭。", "grammar": "频率 usually+once"},
            ]
        },
        {
            "name": "Unit 8: be going to",
            "sentences": [
                {"text": "What are you going to do this weekend?", "translation": "你这个周末打算做什么？", "grammar": "be going to 表计划"},
                {"text": "I'm going to visit my grandmother.", "translation": "我打算去看望奶奶。", "grammar": "be going to + 动词原形"},
                {"text": "She's going to buy a new dress.", "translation": "她打算买一条新裙子。", "grammar": "be going to 第三人称"},
                {"text": "What are you going to be when you grow up?", "translation": "你长大后想成为什么？", "grammar": "be going to 将来"},
            ]
        },
        {
            "name": "Unit 9: want to do",
            "sentences": [
                {"text": "What do you want to do?", "translation": "你想做什么？", "grammar": "want to do 想要做某事"},
                {"text": "I want to play football.", "translation": "我想踢足球。", "grammar": "want to + 动词原形"},
                {"text": "I want you to help me with my English.", "translation": "我想要你帮我学英语。", "grammar": "want sb to do"},
                {"text": "Do you want to learn English?", "translation": "你想学英语吗？", "grammar": "want to do 疑问句"},
            ]
        },
        {
            "name": "Unit 11: 一般过去时 - be动词",
            "sentences": [
                {"text": "Were you at school yesterday?", "translation": "昨天你在学校吗？", "grammar": "一般过去时 were 疑问"},
                {"text": "Yes, I was. / No, I wasn't.", "translation": "是的，我在。/ 不，我不在。", "grammar": "wasn't = was not"},
                {"text": "She was at home this morning.", "translation": "今天早上她在家里。", "grammar": "was 用于单数"},
                {"text": "They were very happy last night.", "translation": "昨晚他们很开心。", "grammar": "were 用于复数"},
                {"text": "I was ill yesterday.", "translation": "昨天我生病了。", "grammar": "was 过去状态"},
            ]
        },
        {
            "name": "Unit 12-13: 一般过去时 - 动词",
            "sentences": [
                {"text": "I visited my grandmother yesterday.", "translation": "昨天我去看望了奶奶。", "grammar": "规则动词过去式 -ed"},
                {"text": "She played tennis last weekend.", "translation": "上周末她打了网球。", "grammar": "规则动词 played"},
                {"text": "Did you go to school yesterday?", "translation": "昨天你去学校了吗？", "grammar": "Did + 主语 + 动词原形？"},
                {"text": "Yes, I did. / No, I didn't.", "translation": "是的，我去了。/ 不，我没去。", "grammar": "didn't = did not"},
                {"text": "What did you do last weekend?", "translation": "上周末你做了什么？", "grammar": "What did + 主语 + do?"},
            ]
        },
        {
            "name": "Unit 3: 名词性物主代词",
            "sentences": [
                {"text": "Whose is this book?", "translation": "这本书是谁的？", "grammar": "Whose 提问归属"},
                {"text": "It's mine.", "translation": "这是我的。", "grammar": "mine = my book"},
                {"text": "Is this your bag?", "translation": "这是你的包吗？", "grammar": "your 形容词性物主代词"},
                {"text": "No, it's hers.", "translation": "不，这是她的。", "grammar": "hers = her bag"},
                {"text": "These shoes are theirs.", "translation": "这些鞋是他们的。", "grammar": "theirs = their shoes"},
            ]
        },
        {
            "name": "Unit 4: 祈使句",
            "sentences": [
                {"text": "Open the door, please.", "translation": "请开门。", "grammar": "肯定祈使句"},
                {"text": "Don't be late!", "translation": "别迟到！", "grammar": "否定祈使句 Don't + 动词原形"},
                {"text": "Don't take your gloves off.", "translation": "别脱下手套。", "grammar": "否定祈使句"},
                {"text": "Sit down, please.", "translation": "请坐下。", "grammar": "祈使句"},
                {"text": "Listen to me carefully.", "translation": "认真听我说。", "grammar": "祈使句 listen to"},
            ]
        },
    ]
}


# === 理解题题库 (按语法点) ===
COMPREHENSION_QUESTIONS = {
    "现在进行时": [
        {"question": "What are you doing now?", "options": ["I am reading", "I read", "I will read"], "answer": 0},
        {"question": "Is she playing tennis?", "options": ["Yes, she is", "Yes, she does", "No, she don't"], "answer": 0},
    ],
    "一般现在时": [
        {"question": "He ___ English every day. (like)", "options": ["like", "likes", "liking"], "answer": 1},
        {"question": "When ___ you get up? (do)", "options": ["does", "do", "is"], "answer": 1},
    ],
    "频率": [
        {"question": "I go swimming ___ a week. (two)", "options": ["twice", "two time", "second"], "answer": 0},
        {"question": "___ do you exercise? - Every day.", "options": ["How many", "How often", "What time"], "answer": 1},
    ],
    "be going to": [
        {"question": "What ___ you ___ to do tomorrow? (plan)", "options": ["are, going", "do, want", "did, going"], "answer": 0},
    ],
    "一般过去时": [
        {"question": "I ___ to Beijing last year. (go)", "options": ["go", "went", "going"], "answer": 1},
        {"question": "___ you ___ your homework yesterday?", "options": ["Did, do", "Do, did", "Does, do"], "answer": 0},
    ],
    "名词性物主代词": [
        {"question": "This is my book. It's ___ .", "options": ["mine", "my", "me"], "answer": 0},
        {"question": "Is this ___ bag? - No, it's hers.", "options": ["your", "yours", "you"], "answer": 0},
    ],
    "祈使句": [
        {"question": "___ late! It's impolite.", "options": ["Don't be", "Not be", "Be not"], "answer": 0},
    ],
}


def register_routes(app):
    @app.route('/api/course')
    def get_course():
        """获取课程内容"""
        return jsonify({"success": True, "course": COURSE_CONTENT})

    @app.route('/api/unit/<int:unit_id>')
    def get_unit(unit_id):
        """获取指定单元"""
        if 0 <= unit_id < len(COURSE_CONTENT["units"]):
            return jsonify({"success": True, "unit": COURSE_CONTENT["units"][unit_id]})
        return jsonify({"success": False, "error": "单元不存在"})

    @app.route('/api/sentences/<int:unit_id>')
    def get_sentences(unit_id):
        """获取单元句子"""
        if 0 <= unit_id < len(COURSE_CONTENT["units"]):
            return jsonify({"success": True, "sentences": COURSE_CONTENT["units"][unit_id]["sentences"]})
        return jsonify({"success": False, "error": "单元不存在"})

    @app.route('/api/question/<topic>')
    def get_question(topic):
        """获取理解题"""
        questions = COMPREHENSION_QUESTIONS.get(topic, [])
        if questions:
            q = random.choice(questions)
            return jsonify({"success": True, "question": q})
        return jsonify({"success": False, "error": "没有相关题目"})