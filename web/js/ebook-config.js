// ============================================
// Shadow Ebook - 配置文件
// ============================================

const ShadowConfig = {
    // 版本
    VERSION: '2.0.0',
    
    // API配置
    DICT_API: 'https://api.dictionaryapi.dev/api/v2/entries/en/',
    MEMORY_API: 'https://api.mymemory.translated.net/get',
    
    // TTS配置
    TTS_BASE_URL: '/api/tts',
    TTS_TIMEOUT: 15000,
    
    // 复习间隔（天）
    REVIEW_INTERVALS: [1, 3, 7, 14, 30, 60],
    
    // 蓝思值范围
    LEXILE_RANGES: {
        'A': [0, 200],
        'B': [200, 400],
        'C': [400, 600],
        'D': [600, 800],
        'E': [800, 1000],
        'F': [1000, 1200],
        'G': [1200, 1400]
    },
    
    // 颜色配置
    COLORS: {
        primary: '#6366F1',
        secondary: '#10B981',
        warning: '#F59E0B',
        danger: '#EF4444',
        info: '#3B82F6'
    },
    
    // 书籍配置
    BOOKS: {
        'new-concept-2a': {
            id: 'new-concept-2a',
            title: '新概念英语青少版 2A',
            author: '新概念团队',
            level: 'A2',
            lexile: 400,
            description: '适合初学者的基础英语教程'
        },
        'magic-tree-house-29': {
            id: 'magic-tree-house-29',
            title: 'Magic Tree House #29',
            author: 'Mary Pope Osborne',
            level: 'M',
            lexile: 510,
            description: '圣诞魔法屋 - 经典儿童冒险小说'
        },
        'harry-potter-1': {
            id: 'harry-potter-1',
            title: "Harry Potter #1",
            author: 'J.K. Rowling',
            level: 'T',
            lexile: 880,
            description: '哈利波特与魔法石 - 经典奇幻小说'
        }
    },
    
    // 存储键名
    STORAGE_KEYS: {
        STATS: 'shadowStats',
        VOCABULARY: 'shadowVocabulary',
        SETTINGS: 'shadowSettings',
        BOOK_PROGRESS: 'shadowBookProgress',
        THEME: 'shTheme',
        KID_MODE: 'kidMode',
        LAST_BOOK: 'lastBookId',
        VOICE: 'selectedVoice'
    },
    
    // 默认设置
    DEFAULT_SETTINGS: {
        voice: 'en-US-AriaNeural',
        theme: 'system',
        fontSize: 'medium',
        autoPlay: false,
        showTranslation: true
    }
};

// 导出
window.ShadowConfig = ShadowConfig;