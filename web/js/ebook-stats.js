// ============================================
// Shadow Ebook - 统计模块
// ============================================

const Stats = {
    STORAGE_KEY: 'shadowStats',
    
    // 获取统计数据
    getData() {
        const data = localStorage.getItem(this.STORAGE_KEY);
        return data ? JSON.parse(data) : {
            totalMinutes: 0,
            totalBooks: 0,
            streakDays: 0,
            lastStudyDate: null,
            weeklyMinutes: {},
            recentActivities: [],
            dailyLimit: 0,
            todayMinutes: 0,
            todayStart: null
        };
    },
    
    // 保存统计数据
    saveData(data) {
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(data));
    },
    
    // 开始学习会话
    startSession() {
        const data = this.getData();
        const today = new Date().toDateString();
        
        // 检查是否是同一天
        if (data.lastStudyDate !== today) {
            // 更新连续天数
            const yesterday = new Date();
            yesterday.setDate(yesterday.getDate() - 1);
            
            if (data.lastStudyDate === yesterday.toDateString()) {
                data.streakDays++;
            } else if (data.lastStudyDate !== today) {
                data.streakDays = 1;
            }
            
            data.lastStudyDate = today;
            data.todayMinutes = 0;
            data.todayStart = Date.now();
        }
        
        this.saveData(data);
        return data;
    },
    
    // 记录学习时间
    addMinutes(minutes) {
        const data = this.getData();
        const today = new Date();
        const dayName = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][today.getDay()];
        
        data.totalMinutes += minutes;
        data.todayMinutes += minutes;
        
        // 更新周统计
        data.weeklyMinutes[dayName] = (data.weeklyMinutes[dayName] || 0) + minutes;
        
        this.saveData(data);
        return data;
    },
    
    // 添加活动记录
    addActivity(type, title, duration = '') {
        const data = this.getData();
        const now = new Date();
        
        const activity = {
            type,
            title,
            duration,
            time: now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
            timestamp: now.getTime()
        };
        
        data.recentActivities.unshift(activity);
        
        // 保留最近20条
        if (data.recentActivities.length > 20) {
            data.recentActivities = data.recentActivities.slice(0, 20);
        }
        
        this.saveData(data);
    },
    
    // 获取今日进度
    getTodayProgress() {
        const data = this.getData();
        const today = new Date().toDateString();
        
        if (data.lastStudyDate !== today) {
            return { minutes: 0, limit: data.dailyLimit, exceeded: false };
        }
        
        return {
            minutes: data.todayMinutes,
            limit: data.dailyLimit,
            exceeded: data.dailyLimit > 0 && data.todayMinutes >= data.dailyLimit
        };
    },
    
    // 设置每日限制
    setDailyLimit(minutes) {
        const data = this.getData();
        data.dailyLimit = minutes;
        this.saveData(data);
    },
    
    // 更新书籍数
    incrementBooks() {
        const data = this.getData();
        data.totalBooks++;
        this.saveData(data);
    },
    
    // 获取周学习数据
    getWeeklyData() {
        const data = this.getData();
        const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
        
        return days.map(day => ({
            day,
            minutes: data.weeklyMinutes[day] || 0
        }));
    },
    
    // 重置数据
    reset() {
        localStorage.removeItem(this.STORAGE_KEY);
    },
    
    // 导出数据
    export() {
        return JSON.stringify(this.getData(), null, 2);
    },
    
    // 导入数据
    import(jsonStr) {
        try {
            const data = JSON.parse(jsonStr);
            this.saveData(data);
            return true;
        } catch (e) {
            console.error('Import failed:', e);
            return false;
        }
    }
};

// 导出
window.Stats = Stats;