
        // ========== 家长监控 JS (server-side auth) ==========

        // XSS 防御: 所有外部数据走 textContent
        const el = (id) => document.getElementById(id);

        function setText(id, text) { el(id).textContent = text ?? ''; }

        function showPwdError(msg) {
            el('pwdError').textContent = msg;
            el('pwdError').style.display = 'block';
        }

        function showPwdRemaining(n) {
            // R11: 后端返的 remaining 字段给家长看"还剩 N 次"
            const box = el('pwdRemaining');
            if (typeof n === 'number' && n > 0 && n <= 4) {
                box.textContent = `⚠️ 还剩 ${n} 次尝试, 之后会锁定 15 分钟`;
                box.style.display = 'block';
            } else if (n === 0) {
                box.textContent = '🔒 已锁定, 请稍后再试';
                box.style.display = 'block';
            } else {
                box.style.display = 'none';
            }
        }

        function clearPwdInputs() {
            document.querySelectorAll('.pwd-digit').forEach(i => i.value = '');
            el('pwd1').focus();
        }

        // 初始化
        document.addEventListener('DOMContentLoaded', async () => {
            initPasswordInputs();
            try {
                const r = await fetch('/api/parent/check', { credentials: 'same-origin' });
                const j = await r.json();
                if (j.authenticated) showDashboard();
            } catch (e) {
                console.warn('auth check failed', e);
            }
        });

        // 密码输入处理
        function initPasswordInputs() {
            const inputs = document.querySelectorAll('.pwd-digit');
            inputs.forEach((input, index) => {
                input.addEventListener('input', () => {
                    if (input.value.length === 1 && index < inputs.length - 1) {
                        inputs[index + 1].focus();
                    }
                    const pwd = Array.from(inputs).map(i => i.value).join('');
                    if (pwd.length === 4) checkPassword(pwd);
                });
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Backspace' && input.value === '' && index > 0) {
                        inputs[index - 1].focus();
                    }
                });
            });
        }

        async function checkPassword(pwd) {
            try {
                const r = await fetch('/api/parent/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ pin: pwd })
                });
                const j = await r.json();
                if (j.success) {
                    el('pwdError').style.display = 'none';
                    el('pwdRemaining').style.display = 'none';
                    // R10: 如果 URL 带 ?next=/ebook, 登录后跳回去, 避免家长手动返回
                    const next = new URLSearchParams(location.search).get('next');
                    if (next && next.startsWith('/')) {
                        window.location.href = next;
                        return;
                    }
                    showDashboard();
                } else {
                    showPwdError(j.error || 'PIN 错误');
                    showPwdRemaining(j.remaining);
                    clearPwdInputs();
                }
            } catch (e) {
                showPwdError('网络错误');
                clearPwdInputs();
            }
        }

        async function showDashboard() {
            el('loginSection').classList.add('hidden');
            el('dashboardSection').classList.remove('hidden');
            await loadStats();
        }

        async function logout() {
            try {
                await fetch('/api/parent/logout', {
                    method: 'POST', credentials: 'same-origin'
                });
            } catch (e) { /* 即使网络错误也继续清 UI */ }
            el('dashboardSection').classList.add('hidden');
            el('loginSection').classList.remove('hidden');
            clearPwdInputs();
            el('pwdError').style.display = 'none';
        }

        async function showChangePwd() {
            const current = prompt('请输入当前 PIN:');
            if (!current) return;
            if (!/^\d{4}$/.test(current)) { alert('PIN 必须是 4 位数字'); return; }
            const newPin = prompt('请输入新 PIN (4 位数字):');
            if (!newPin) return;
            if (!/^\d{4}$/.test(newPin)) { alert('新 PIN 必须是 4 位数字'); return; }
            try {
                const r = await fetch('/api/parent/change-pin', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    body: JSON.stringify({ current, new: newPin })
                });
                const j = await r.json();
                alert(j.success ? 'PIN 修改成功' : (j.error || '修改失败'));
            } catch (e) {
                alert('网络错误');
            }
        }

        // 加载统计数据 (从 server)
        async function loadStats() {
            let payload = { stats: {}, vocabulary: {}, settings: {} };
            try {
                const r = await fetch('/api/parent/data', { credentials: 'same-origin' });
                if (r.ok) {
                    const j = await r.json();
                    payload = j.data || payload;
                }
            } catch (e) {
                console.warn('load parent data failed', e);
            }
            // R12: 真 vocab 状态机数据 (从 /api/vocab/stats 拿真计数)
            //      + 阅读进度 (/api/progress)
            //      + 句子熟练度汇总
            const [vocabStats, bookProgress, booksList] = await Promise.all([
                fetch('/api/vocab/stats').then(r => r.json()).catch(() => null),
                fetch('/api/progress').then(r => r.json()).catch(() => null),
                fetch('/api/books').then(r => r.json()).catch(() => null),
            ]);
            renderDashboard(payload, { vocabStats, bookProgress, booksList });
            loadSettings(payload.settings || {});
        }

        function renderDashboard({ stats = {}, vocabulary = {} }, extras = {}) {
            const { vocabStats, bookProgress, booksList } = extras;

            // 概览
            setText('totalBooks', stats.totalBooks ?? 0);
            setText('totalMinutes', stats.totalMinutes ?? 0);
            setText('streakDays', stats.streakDays ?? 0);
            setText('newWords', (vocabulary.newWords || []).length);

            // 周图表
            renderWeeklyChart(stats.weeklyMinutes || {});

            // 词汇分布: 优先用 R12 真状态机数据 (有 SRS 才有意义)
            const dist = vocabStats || vocabulary.masteryDistribution || { learning: 0, practicing: 0, familiar: 0, mastered: 0 };
            setText('vocabLearning', dist.learning ?? 0);
            setText('vocabPracticing', dist.practicing ?? 0);
            setText('vocabFamiliar', dist.familiar ?? 0);
            setText('vocabMastered', dist.mastered ?? 0);

            const total = (dist.learning || 0) + (dist.practicing || 0) + (dist.familiar || 0) + (dist.mastered || 0);
            renderVocabBar(dist, total);

            // R12: 显示今日到期复习数
            const dueEl = document.getElementById('vocabDueNow');
            if (dueEl && typeof dist.due_now === 'number') {
                dueEl.textContent = dist.due_now;
                dueEl.style.display = dist.due_now > 0 ? '' : 'none';
            }

            // R12: per-book 阅读进度
            renderBookProgress(bookProgress?.progress || {}, booksList?.books || []);

            // 最近活动
            renderActivityList(stats.recentActivities || []);
        }

        function renderBookProgress(progress, books) {
            const box = document.getElementById('bookProgressList');
            if (!box) return;
            box.innerHTML = '';
            const titles = new Map((books || []).map(b => [b.id, b.title || b.id]));
            const ids = Object.keys(progress || {});
            if (ids.length === 0) {
                box.innerHTML = '<div style="color:#999;padding:8px 0;">孩子还没读过任何书</div>';
                return;
            }
            ids.sort((a, b) => (progress[b].last_open_ts || 0) - (progress[a].last_open_ts || 0));
            for (const id of ids.slice(0, 8)) {
                const p = progress[id];
                const li = document.createElement('div');
                li.className = 'book-progress-item';
                li.innerHTML = `
                    <div class="book-progress-title">${titles.get(id) || id}</div>
                    <div class="book-progress-meta">📍 第 ${p.chapter_idx + 1} 章 · 第 ${p.sentence_idx + 1} 句</div>`;
                box.appendChild(li);
            }
        }

        function renderVocabBar(dist, total) {
            const bar = el('vocabBar');
            bar.innerHTML = '';
            if (total <= 0) return;
            const segs = [
                ['learning', dist.learning || 0],
                ['practicing', dist.practicing || 0],
                ['familiar', dist.familiar || 0],
                ['mastered', dist.mastered || 0]
            ];
            for (const [cls, val] of segs) {
                if (val <= 0) continue;
                const div = document.createElement('div');
                div.className = 'segment ' + cls;
                div.style.width = ((val / total) * 100).toFixed(0) + '%';
                bar.appendChild(div);
            }
        }

        function renderActivityList(activities) {
            const list = el('activityList');
            list.innerHTML = '';
            const data = activities.length > 0 ? activities.slice(0, 10) : [null];
            for (const act of data) {
                const li = document.createElement('li');
                li.className = 'activity-item';
                const icon = document.createElement('div');
                icon.className = 'icon';
                icon.textContent = act?.icon || '📖';
                const info = document.createElement('div');
                info.className = 'info';
                const title = document.createElement('div');
                title.className = 'title';
                title.textContent = act?.title || '暂无活动记录';
                const time = document.createElement('div');
                time.className = 'time';
                time.textContent = act?.time || '开始学习后显示';
                info.appendChild(title);
                info.appendChild(time);
                li.appendChild(icon);
                li.appendChild(info);
                if (act?.duration) {
                    const dur = document.createElement('div');
                    dur.className = 'duration';
                    dur.textContent = act.duration;
                    li.appendChild(dur);
                }
                list.appendChild(li);
            }
        }

        function renderWeeklyChart(weeklyMinutes) {
            const days = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
            const chart = el('weeklyChart');
            chart.innerHTML = '';
            const maxMinutes = Math.max(30, ...Object.values(weeklyMinutes).map(Number).filter(n => !isNaN(n)));
            const today = new Date().getDay();
            const mondayIndex = today === 0 ? 6 : today - 1;
            const orderedDays = [...days.slice(mondayIndex), ...days.slice(0, mondayIndex)];
            for (const day of orderedDays) {
                const minutes = Number(weeklyMinutes[day] || 0);
                const height = minutes > 0 ? (minutes / maxMinutes * 100) : 5;
                const bar = document.createElement('div');
                bar.className = 'chart-bar';
                bar.style.height = height + '%';
                const dayLabel = document.createElement('span');
                dayLabel.className = 'day-label';
                dayLabel.textContent = day;
                bar.appendChild(dayLabel);
                if (minutes > 0) {
                    const timeLabel = document.createElement('span');
                    timeLabel.className = 'time-label';
                    timeLabel.textContent = minutes + 'm';
                    bar.appendChild(timeLabel);
                }
                chart.appendChild(bar);
            }
        }

        // 每日学习时间上限 (本地设置, 不用同步到 server)
        function loadSettings(serverSettings) {
            const tl = localStorage.getItem('dailyTimeLimit') || '0';
            const elTl = el('timeLimit');
            const elEn = el('enableTimeLimit');
            elTl.value = tl;
            elEn.checked = localStorage.getItem('enableTimeLimit') === 'true';

            elTl.onchange = (e) => localStorage.setItem('dailyTimeLimit', e.target.value);
            elEn.onchange = (e) => localStorage.setItem('enableTimeLimit', e.target.checked);
        }

        // 导出 (从 server 拉)
        async function exportData(format) {
            try {
                if (format === 'json') {
                    const r = await fetch('/api/parent/export', { credentials: 'same-origin' });
                    if (!r.ok) { alert('导出失败: ' + r.status); return; }
                    const blob = await r.blob();
                    downloadBlob(blob, 'shadow_learning_data.json');
                } else {
                    // CSV 从 server 拉的 JSON 里抽 vocab
                    const r = await fetch('/api/parent/data', { credentials: 'same-origin' });
                    const j = await r.json();
                    const vocabList = (j.data?.vocabulary?.newWords) || [];
                    const csv = '单词,掌握度,复习次数,最后复习时间\n' +
                        vocabList.map(w => `${w.word || ''},${w.mastery || 0},${w.reviewCount || 0},${w.lastReview || ''}`).join('\n');
                    downloadBlob(new Blob([csv], { type: 'text/csv' }), 'shadow_vocabulary.csv');
                }
            } catch (e) {
                alert('导出失败');
            }
        }

        function downloadBlob(blob, filename) {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = filename;
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 100);
        }

        async function resetData() {
            if (!confirm('确定要重置所有学习记录吗？此操作不可撤销！')) return;
            if (!confirm('再次确认：清除所有学习数据？')) return;
            try {
                const r = await fetch('/api/parent/reset', {
                    method: 'POST', credentials: 'same-origin'
                });
                const j = await r.json();
                if (j.success) {
                    await loadStats();
                    alert('学习记录已重置');
                } else {
                    alert('重置失败: ' + (j.error || ''));
                }
            } catch (e) {
                alert('网络错误');
            }
        }
    