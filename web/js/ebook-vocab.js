// ============================================
// Shadow Ebook - 词汇管理模块（艾宾浩斯复习）
// ============================================

const Vocabulary = {
    STORAGE_KEY: 'shadowVocabulary',
    
    // 获取词汇数据
    getData() {
        const data = localStorage.getItem(this.STORAGE_KEY);
        return data ? JSON.parse(data) : {
            words: [],
            newWords: [],
            reviewDates: {}
        };
    },
    
    // 保存词汇数据
    saveData(data) {
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(data));
    },
    
    // 添加生词
    addWord(word, context = '') {
        const data = this.getData();
        
        // 检查是否已存在
        if (data.words.find(w => w.word === word)) {
            return false;
        }
        
        const now = Date.now();
        const wordObj = {
            word,
            context,
            addedAt: now,
            lastReview: null,
            nextReview: now,
            reviewCount: 0,
            mastery: 0, // 0-100
            interval: 1,
            easeFactor: 2.5
        };
        
        data.words.push(wordObj);
        data.newWords.push(word);
        this.saveData(data);
        
        return true;
    },
    
    // 提交复习结果
    submitReview(word, quality) {
        // quality: 1=完全忘记 2=忘记 3=模糊 4=记住 5=完全记住
        const data = this.getData();
        const wordObj = data.words.find(w => w.word === word);
        
        if (!wordObj) return null;
        
        const now = Date.now();
        const intervals = [1, 3, 7, 14, 30, 60]; // 天数
        
        // 计算新的掌握度
        let masteryChange = 0;
        if (quality >= 4) {
            masteryChange = 20;
            // 延长复习间隔
            const idx = intervals.indexOf(wordObj.interval);
            if (idx < intervals.length - 1) {
                wordObj.interval = intervals[idx + 1];
            }
        } else if (quality === 3) {
            masteryChange = 5;
        } else {
            masteryChange = -10;
            // 缩短间隔
            wordObj.interval = 1;
        }
        
        wordObj.mastery = Math.max(0, Math.min(100, wordObj.mastery + masteryChange));
        wordObj.reviewCount++;
        wordObj.lastReview = now;
        wordObj.nextReview = now + (wordObj.interval * 24 * 60 * 60 * 1000);
        
        this.saveData(data);
        
        return {
            mastery: wordObj.mastery,
            nextReview: wordObj.nextReview
        };
    },
    
    // 获取待复习单词
    getDueWords(limit = 10) {
        const data = this.getData();
        const now = Date.now();
        
        return data.words
            .filter(w => w.nextReview <= now)
            .sort((a, b) => a.nextReview - b.nextReview)
            .slice(0, limit);
    },
    
    // 获取新单词
    getNewWords(limit = 5) {
        const data = this.getData();
        return data.newWords.slice(0, limit);
    },
    
    // 获取词汇统计
    getStats() {
        const data = this.getData();
        const dist = { learning: 0, practicing: 0, familiar: 0, mastered: 0 };
        
        data.words.forEach(w => {
            if (w.mastery < 30) dist.learning++;
            else if (w.mastery < 60) dist.practicing++;
            else if (w.mastery < 90) dist.familiar++;
            else dist.mastered++;
        });
        
        return {
            total: data.words.length,
            distribution: dist,
            averageMastery: data.words.length > 0 
                ? Math.round(data.words.reduce((sum, w) => sum + w.mastery, 0) / data.words.length) 
                : 0
        };
    },
    
    // 删除单词
    removeWord(word) {
        const data = this.getData();
        data.words = data.words.filter(w => w.word !== word);
        data.newWords = data.newWords.filter(w => w !== word);
        this.saveData(data);
    },
    
    // 导出词汇
    export(format = 'json') {
        const data = this.getData();
        
        if (format === 'csv') {
            let csv = '单词,掌握度,复习次数,间隔,添加时间,最后复习\n';
            data.words.forEach(w => {
                csv += `${w.word},${w.mastery}%,${w.reviewCount},${w.interval}天,${new Date(w.addedAt).toLocaleDateString()},${w.lastReview ? new Date(w.lastReview).toLocaleDateString() : '未复习'}\n`;
            });
            return csv;
        }
        
        return JSON.stringify(data, null, 2);
    },
    
    // 导入词汇
    import(data, format = 'json') {
        try {
            const imported = format === 'json' ? JSON.parse(data) : this.parseCSV(data);
            
            if (Array.isArray(imported.words)) {
                const current = this.getData();
                const merged = [...current.words];
                
                imported.words.forEach(newWord => {
                    if (!merged.find(w => w.word === newWord.word)) {
                        merged.push(newWord);
                    }
                });
                
                this.saveData({ ...current, words: merged });
                return true;
            }
        } catch (e) {
            console.error('Import failed:', e);
        }
        return false;
    },
    
    // 解析CSV
    parseCSV(csv) {
        const lines = csv.split('\n').filter(l => l.trim());
        const words = [];
        
        lines.slice(1).forEach(line => {
            const parts = line.split(',');
            if (parts.length >= 2) {
                words.push({
                    word: parts[0],
                    mastery: parseInt(parts[1]) || 0,
                    reviewCount: parseInt(parts[2]) || 0,
                    interval: parseInt(parts[3]) || 1
                });
            }
        });
        
        return { words };
    }
};

// 导出
window.Vocabulary = Vocabulary;