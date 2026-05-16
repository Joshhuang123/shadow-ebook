// ============================================
// Shadow Ebook - 词典查询模块
// ============================================

const Dictionary = {
    cache: {},
    
    // 查词
    async lookup(word) {
        const normalized = word.toLowerCase().trim();
        
        // 先检查缓存
        if (this.cache[normalized]) {
            return this.cache[normalized];
        }
        
        try {
            // 调用Dictionary API
            const response = await fetch(`https://api.dictionaryapi.dev/api/v2/entries/en/${normalized}`);
            
            if (!response.ok) {
                // 尝试翻译API
                return await this.translateFallback(normalized);
            }
            
            const data = await response.json();
            const result = this.parseDictionaryResult(data);
            
            // 存入缓存
            this.cache[normalized] = result;
            return result;
            
        } catch (error) {
            console.log('Dict lookup failed:', error);
            return await this.translateFallback(normalized);
        }
    },
    
    // 解析词典结果
    parseDictionaryResult(data) {
        if (!data || !data.length) return null;
        
        const entry = data[0];
        const meanings = entry.meanings || [];
        
        // 提取音标和发音
        const phonetics = entry.phonetics || [];
        const phonetic = phonetics.length > 0 ? phonetics[0].text : '';
        const audioUrl = phonetics.find(p => p.audio)?.audio || '';
        
        // 提取释义
        const definitions = meanings.map(m => {
            const partOfSpeech = m.partOfSpeech || '';
            const defs = (m.definitions || []).slice(0, 3).map(d => d.definition);
            return { partOfSpeech, definitions: defs };
        });
        
        return {
            word: entry.word,
            phonetic,
            audioUrl,
            meanings,
            definitions: definitions.slice(0, 3)
        };
    },
    
    // 翻译后备方案
    async translateFallback(word) {
        try {
            const response = await fetch(
                `https://api.mymemory.translated.net/get?q=${encodeURIComponent(word)}&lang=en=zh`
            );
            const data = await response.json();
            
            return {
                word,
                phonetic: '',
                audioUrl: '',
                translation: data.responseData?.translatedText || '',
                isTranslation: true
            };
        } catch (error) {
            return { word, translation: '未找到释义', isTranslation: true };
        }
    },
    
    // 播放发音
    async playAudio(word, voice = 'en-US-AriaNeural') {
        // 使用Web Speech API
        if ('speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(word);
            utterance.voice = speechSynthesis.getVoices().find(v => v.name.includes(voice.split('-')[2])) || null;
            utterance.rate = 0.9;
            utterance.pitch = 1;
            speechSynthesis.speak(utterance);
        }
    },
    
    // 清除缓存
    clearCache() {
        this.cache = {};
    }
};

// 导出
window.Dictionary = Dictionary;