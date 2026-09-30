
        // 状态
        let bookData = null;
        let currentBookId = null;
        let currentChapterIndex = 0;
        let currentSentenceIndex = 0;
        let sentences = [];
        // chapterStarts[i] = 第 i 章第一句在全书 sentences 里的下标。
        // 全书拍平成一条流之后,翻页才能从本章末屏直接接到下一章首屏。
        let chapterStarts = [];
        // 每屏句数与阅读形态由「书的蓝思值 - 孩子的蓝思值」算出,不是写死的。
        // 权威公式在 extensions/books.py 的 calc_reading_density(),
        // 这里的表必须和它逐档一致(tests/test_reading_density.py 有 parity 测试)。
        let sentencesPerPage = 3;
        let readingMode = 'focus';
        let childProfile = { name: '', age: null, lexile: null };
        // 没建档案时按「刚够读」处理;和后端 DEFAULT_CHILD_LEXILE 一致。
        const DEFAULT_CHILD_LEXILE = 600;
        const READING_DENSITY_STEPS = [
            [-200, 10, 'book'],
            [-50, 7, 'book'],
            [50, 5, 'focus'],
            [150, 4, 'focus'],
            [null, 3, 'focus'],
        ];
        let audioElement = null;
        let currentAudioUrl = null;  // 当前 audioElement 的 blob URL, 用于 revoke
        let isPlaying = false;
        let ttsRequestSeq = 0;  // 单调递增, 丢弃过期响应, 防止双击叠音
        let currentWord = null;
        let vocabulary = JSON.parse(localStorage.getItem('vocabulary') || '[]');
        let lookedWords = JSON.parse(localStorage.getItem('lookedWords') || '{}');

        // XSS 防御: 字典 API / 翻译 API / 生词本 等所有外部数据用这个转义后再 innerHTML
        const _escMap = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
        const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, c => _escMap[c]);

        // TTS音色设置
        let currentVoice = localStorage.getItem('ttsVoice') || 'en-US-AriaNeural';

        // ==================== IndexedDB TTS 缓存管理 ====================
        class AudioCacheManager {
            constructor() {
                this.dbName = 'ShadowEbookTTS';
                this.dbVersion = 1;
                this.storeName = 'audio_cache';
                this.db = null;
                this.cacheProgress = {};
            }

            async open() {
                return new Promise((resolve, reject) => {
                    const request = indexedDB.open(this.dbName, this.dbVersion);
                    request.onerror = () => reject(request.error);
                    request.onsuccess = () => { this.db = request.result; resolve(this.db); };
                    request.onupgradeneeded = (event) => {
                        const db = event.target.result;
                        if (!db.objectStoreNames.contains(this.storeName)) {
                            const store = db.createObjectStore(this.storeName, { keyPath: 'id' });
                            store.createIndex('bookId', 'bookId', { unique: false });
                            store.createIndex('sentenceIndex', 'sentenceIndex', { unique: false });
                        }
                    };
                });
            }

            async getSentenceId(bookId, sentenceIndex, text) {
                const textHash = await this.hashText(text + currentVoice);
                return `${bookId}_${sentenceIndex}_${textHash}`;
            }

            async hashText(text) {
                const encoder = new TextEncoder();
                const data = encoder.encode(text);
                const hashBuffer = await crypto.subtle.digest('SHA-256', data);
                const hashArray = Array.from(new Uint8Array(hashBuffer));
                return hashArray.map(b => b.toString(16).padStart(2, '0')).join('').substring(0, 16);
            }

            async getAudio(bookId, sentenceIndex, text) {
                await this.ensureOpen();
                const id = await this.getSentenceId(bookId, sentenceIndex, text);
                return new Promise((resolve, reject) => {
                    const tx = this.db.transaction(this.storeName, 'readonly');
                    const request = tx.objectStore(this.storeName).get(id);
                    request.onerror = () => reject(request.error);
                    request.onsuccess = () => resolve(request.result?.audio || null);
                });
            }

            async saveAudio(bookId, sentenceIndex, text, audioBlob) {
                await this.ensureOpen();
                const id = await this.getSentenceId(bookId, sentenceIndex, text);
                return new Promise((resolve, reject) => {
                    const tx = this.db.transaction(this.storeName, 'readwrite');
                    const request = tx.objectStore(this.storeName).put({
                        id, bookId, sentenceIndex, text, audio: audioBlob,
                        voice: currentVoice, cachedAt: Date.now()
                    });
                    request.onerror = () => reject(request.error);
                    request.onsuccess = () => {
                        if (!this.cacheProgress[bookId]) this.cacheProgress[bookId] = { cached: 0, total: 0 };
                        this.cacheProgress[bookId].cached++;
                        resolve(id);
                    };
                });
            }

            async getBookProgress(bookId) {
                await this.ensureOpen();
                return new Promise((resolve, reject) => {
                    const tx = this.db.transaction(this.storeName, 'readonly');
                    const request = tx.objectStore(this.storeName).index('bookId').getAll(bookId);
                    request.onerror = () => reject(request.error);
                    request.onsuccess = () => {
                        const cached = request.result || [];
                        resolve({ cached: cached.length, total: this.cacheProgress[bookId]?.total || 0 });
                    };
                });
            }

            setBookTotal(bookId, total) {
                if (!this.cacheProgress[bookId]) this.cacheProgress[bookId] = { cached: 0, total: 0 };
                this.cacheProgress[bookId].total = total;
            }

            async clearBookCache(bookId) {
                await this.ensureOpen();
                return new Promise((resolve, reject) => {
                    const tx = this.db.transaction(this.storeName, 'readwrite');
                    const cursor = tx.objectStore(this.storeName).index('bookId').openCursor(bookId);
                    cursor.onerror = () => reject(cursor.error);
                    cursor.onsuccess = (event) => {
                        const cur = event.target.result;
                        if (cur) { cur.delete(); cur.continue(); }
                        else { if (this.cacheProgress[bookId]) this.cacheProgress[bookId].cached = 0; resolve(); }
                    };
                });
            }

            async ensureOpen() {
                if (!this.db) await this.open();
            }
        }

        const audioCache = new AudioCacheManager();
        audioCache.open().catch(console.error);

        // 初始化音色选择器
        document.getElementById('voice-select').value = currentVoice;
        document.getElementById('voice-select').addEventListener('change', (e) => changeVoice(e.target.value));

        function changeVoice(voice) {
            currentVoice = voice;
            localStorage.setItem('ttsVoice', voice);
        }

        // 艾宾浩斯复习间隔（天）
        const REVIEW_INTERVALS = [1, 3, 7, 14, 30];

        // 复习数据
        let reviewQueue = [];
        let currentReviewIndex = 0;
        let reviewCorrect = 0;
        let reviewWrong = 0;

        // 录音状态
        let isRecording = false;
        let mediaRecorder = null;
        let audioChunks = [];
        let recognition = null;
        let currentMode = 'read';  // 'read' 或 'shadow'

        // 初始化
        updateVocabCount();
        updateReviewReminder();
        loadBookList();

        // 显示书籍列表
        function showBookList() {
            document.getElementById('book-list-page').classList.remove('hidden');
            document.getElementById('reader-page').classList.remove('active');
            loadBookList();
        }

        // 显示阅读器
        function showReader() {
            initFontSize();
            document.getElementById('book-list-page').classList.add('hidden');
            document.getElementById('reader-page').classList.add('active');
        }

        // R10: 全局缓存家长登录状态, 让 import 卡片显示"需先登录"提示
        let parentAuthed = false;
        async function refreshParentAuth() {
            try {
                const r = await fetch('/api/parent/check');
                const d = await r.json();
                parentAuthed = d.authenticated === true;
            } catch (e) {
                parentAuthed = false;
            }
        }
        // 页面加载时查一次, login/logout 之后再查
        refreshParentAuth();

        // R24: 侧栏从「常驻第三列」改成抽屉。设计稿底栏只有三个动作
        // (字号 / 朗读 / 更多),六块功能全部收进 ☰ 后面。
        function toggleSidebar() {
            const drawer = document.getElementById('sidebar');
            const open = drawer.classList.toggle('open');
            document.getElementById('drawer-scrim').classList.toggle('open', open);
            // 键盘可达:抽屉开着时 Esc 关闭
            if (open) document.addEventListener('keydown', escCloseDrawer);
            else document.removeEventListener('keydown', escCloseDrawer);
        }
        function escCloseDrawer(e) {
            if (e.key === 'Escape') toggleSidebar();
        }
        function closeDrawer() {
            const drawer = document.getElementById('sidebar');
            if (drawer.classList.contains('open')) toggleSidebar();
        }

        // R10: 简易 toast (章节边界未识别等临时提示用)
        function showToast(msg, ms) {
            const t = document.createElement('div');
            t.textContent = msg;
            t.style.cssText = 'position:fixed;top:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.78);color:white;padding:10px 20px;border-radius:8px;z-index:9999;font-size:0.9em;';
            document.body.appendChild(t);
            setTimeout(() => t.remove(), ms || 2500);
        }

        // R22: 书架页渲染 (照设计稿 C)
        // 三段结构:继续读大卡(有进度才出现) / 空状态(没书才出现) / 我的书架网格。
        // 排序按「正在读 → 最近读过 → 剩下的」,不按蓝思值分组 ——
        // 孩子回来时记得的是「上次读那本」,不是「上个月加的那个」。
        async function loadBookList() {
            try {
                const [booksRes, progressRes] = await Promise.all([
                    fetch('/api/books'),
                    fetch('/api/progress').catch(() => ({ json: async () => ({ progress: {} }) })),
                ]);
                const booksData = await booksRes.json();
                const progressMap = (await progressRes.json()).progress || {};

                const books = booksData.success ? booksData.books : [];
                const continueCard = document.getElementById('continue-card');
                const emptyState = document.getElementById('shelf-empty');
                const shelfTitle = document.getElementById('shelf-title');
                const grid = document.getElementById('book-grid');

                if (books.length === 0) {
                    continueCard.hidden = true;
                    shelfTitle.hidden = true;
                    grid.innerHTML = '';
                    emptyState.hidden = false;
                    document.getElementById('shelf-empty-hint').textContent =
                        parentAuthed ? '支持 EPUB 格式' : '导入需要家长先在 /parent 登录';
                    return;
                }

                emptyState.hidden = true;
                shelfTitle.hidden = false;

                // 正在读 = 最近打开过的那本。取一个,其余全部进网格,避免同一本出现两次。
                const currentId = pickContinueBookId(books, progressMap);
                const rest = books
                    .filter(b => b.id !== currentId)
                    .sort((a, b) => lastOpen(b, progressMap) - lastOpen(a, progressMap));

                renderContinueCard(books.find(b => b.id === currentId), progressMap[currentId]);
                document.getElementById('shelf-count').textContent = `(${rest.length})`;
                grid.innerHTML = rest.map(b => shelfCardHtml(b, progressMap[b.id])).join('');

                // 有书时,导入入口放在网格最后一张卡后面
                if (parentAuthed) {
                    grid.insertAdjacentHTML('beforeend', `
                        <div class="import-card" data-action="clickTriggerImportFile">
                            <div class="icon">➕</div>
                            <div class="text">导入新书</div>
                            <div class="hint">支持 EPUB 格式</div>
                        </div>
                    `);
                }

                bindCoverFallbacks(grid);
                bindCoverFallbacks(continueCard);
                // 进度条宽度用 JS 设,不能写进 innerHTML 的 style 属性 ——
                // CSP 的 style-src 'self' 会把内联 style 全丢掉。
                grid.querySelectorAll('.shelf-card-fill').forEach(el => {
                    el.style.width = el.dataset.pct + '%';
                });
            } catch (err) {
                console.error('Failed to load book list:', err);
            }

            // 更新所有书的音频缓存徽章
            updateAllCacheBadges();
        }

        // 最近打开时间;没打开过返回 0(排最后)
        function lastOpen(book, progressMap) {
            const p = progressMap[book.id];
            return (p && p.last_open_ts) || 0;
        }

        // 正在读的那本:最近打开过、且还没读完的里面挑一个。
        // TODO(h-jh): 见下方「你来写」注释。
        function pickContinueBookId(books, progressMap) {
            return books
                .filter(b => progressMap[b.id])
                .sort((a, b) => lastOpen(b, progressMap) - lastOpen(a, progressMap))[0]?.id || null;
        }

        // 占位封面:没封面、或封面文件 404 时顶上。跟有封面的卡片同规格(3:4),
        // 否则同一行卡片高度参差,网格会很难看。
        function coverFallbackHtml(book) {
            return `<div class="shelf-card-cover is-empty">${escapeHtml(book.title)}</div>`;
        }

        // TODO(h-jh): 难度标签。蓝思值分三档,和旧版 getLevelClass 一样的边界。
        function levelTag(book) {
            const l = book.lexile || 0;
            if (l >= 500 && l < 800) return ['beginner', '初级'];
            if (l >= 800 && l <= 1000) return ['intermediate', '中级'];
            if (l > 1000) return ['advanced', '高级'];
            return ['unknown', '未评估'];
        }

        // 进度 = 读过的句子数 / 全书总句数。
        // 不用「章数比」,因为各章长短差很多(有的 8 句有的 15 句),按章算会失真。
        // 当前这句算已读(+1),否则孩子读完整本书的最后一句,进度条停在 99%,永远满不了。
        //
        // 越界:句子数按全书 clamp 到 0~100。chapter_idx 超出实际章节数只可能是
        // 书被重新导入后章节变少,此时「已读完」比「刚开始」更接近事实。
        function computeProgress(book, p) {
            if (!p) return 0;
            const counts = book.chapter_sentences || [];
            const total = counts.reduce((a, b) => a + b, 0);
            if (total <= 0) return 0;

            const before = counts.slice(0, p.chapter_idx).reduce((a, b) => a + b, 0);
            const inChapter = counts[p.chapter_idx] || 0;
            const read = before + Math.min((p.sentence_idx || 0) + 1, inChapter);

            return Math.max(0, Math.min(100, Math.round((read / total) * 100)));
        }

        function renderContinueCard(book, p) {
            const card = document.getElementById('continue-card');
            if (!book || !p) { card.hidden = true; return; }
            card.hidden = false;

            document.getElementById('continue-title').textContent = book.title;
            document.getElementById('continue-author').textContent = book.author || '';
            const cc = document.getElementById('continue-cover');
            cc.innerHTML = book.cover
                ? `<img src="${book.cover}" alt="${escapeHtml(book.title)}">`
                : coverFallbackHtml(book);
            document.getElementById('continue-fill').style.width = computeProgress(book, p) + '%';
            document.getElementById('continue-pos').textContent =
                `第 ${(p.chapter_idx || 0) + 1} 章 / 共 ${book.chapters} 章`;
            const btn = document.getElementById('continue-btn');
            btn.dataset.arg = book.id;
        }

        function shelfCardHtml(book, p) {
            const [cls, label] = levelTag(book);
            const pct = computeProgress(book, p);
            const pos = p ? `第 ${(p.chapter_idx || 0) + 1} / 共 ${book.chapters} 章` : '未开始';
            const cover = book.cover
                ? `<div class="shelf-card-cover"><img src="${book.cover}" alt="${escapeHtml(book.title)}" loading="lazy"></div>`
                : coverFallbackHtml(book);

            return `
                <div class="shelf-card" data-action="loadBook" data-arg="${book.id}">
                    ${cover}
                    <h3 class="shelf-card-title">${escapeHtml(book.title)}</h3>
                    <p class="shelf-card-author">${escapeHtml(book.author || '')}</p>
                    <div class="shelf-card-meta">
                        <span class="level-tag ${cls}">${label}</span>
                        <span>${pos}</span>
                    </div>
                    <div class="shelf-card-bar"><div class="shelf-card-fill" data-pct="${pct}"></div></div>
                    <button class="shelf-card-del" data-action="clickStopDeleteBook"
                            data-arg="${book.id}" data-arg2="${escapeHtml(book.title)}"
                            aria-label="删除《${escapeHtml(book.title)}》">×</button>
                </div>
            `;
        }

        // 封面 404 → 换成占位。旧版有 onerror,重排时漏了会导致卡片显示断图标。
        function bindCoverFallbacks(root) {
            root.querySelectorAll('.shelf-card-cover img, .continue-cover img').forEach(img => {
                img.addEventListener('error', () => {
                    const box = img.parentElement;
                    box.replaceWith(makeFallback(img.alt || '这本书', box.classList.contains('continue-cover')));
                }, { once: true });
            });
        }

        function makeFallback(title, kind) {
            const el = document.createElement('div');
            el.className = kind === 'continue' ? 'continue-cover is-empty' : 'shelf-card-cover is-empty';
            el.textContent = title;
            return el;
        }

        async function updateAllCacheBadges() {
            const badges = document.querySelectorAll('[id^="cache-badge-"]');
            for (const badge of badges) {
                const bookId = badge.id.replace('cache-badge-', '');
                try {
                    const progress = await audioCache.getBookProgress(bookId);
                    if (progress.total > 0 && progress.cached > 0) {
                        badge.textContent = `🔊 ${progress.cached}/${progress.total}`;
                        badge.style.display = 'inline-block';
                    } else {
                        badge.style.display = 'none';
                    }
                } catch (e) {
                    badge.style.display = 'none';
                }
            }
        }

        // 缓存整本书的音频（后台执行）
        async function cacheBookAudio(bookId) {
            const btn = document.querySelector(`.cache-audio-btn[onclick*="${bookId}"]`);
            if (btn) {
                btn.classList.add('caching');
                btn.textContent = '⏳';
            }

            try {
                // 获取书籍数据
                const res = await fetch(`/api/book/${bookId}`);
                const data = await res.json();
                if (!data.success) return;

                const book = data.book;
                let totalSentences = 0;
                book.chapters.forEach(ch => totalSentences += ch.sentences.length);

                // 设置总数
                audioCache.setBookTotal(bookId, totalSentences);

                // 逐句缓存
                let cached = 0;
                for (const chapter of book.chapters) {
                    for (let i = 0; i < chapter.sentences.length; i++) {
                        const text = chapter.sentences[i];
                        if (!text || text.length > 500) continue;

                        // 检查是否已缓存
                        const existing = await audioCache.getAudio(bookId, i, text);
                        if (existing) continue;

                        // 生成并缓存
                        try {
                            const ttsRes = await fetch('/api/tts', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ text, voice: currentVoice })
                            });
                            const ttsData = await ttsRes.json();
                            if (ttsData.success && ttsData.audio_url) {
                                const audioRes = await fetch(ttsData.audio_url);
                                const audioBlob = await audioRes.blob();
                                await audioCache.saveAudio(bookId, i, text, audioBlob);
                                cached++;
                            }
                        } catch (e) {}

                        // 更新进度
                        const badge = document.getElementById(`cache-badge-${bookId}`);
                        if (badge) {
                            badge.textContent = `🔊 ${cached}/${totalSentences}`;
                            badge.style.display = 'inline-block';
                        }
                    }
                }
            } catch (e) {
                console.error('Cache failed:', e);
            }

            if (btn) {
                btn.classList.remove('caching');
                btn.textContent = '🔊';
            }
        }

        // 加载书籍
        async function loadBook(bookId) {
            try {
                const res = await fetch(`/api/book/${bookId}`);
                const data = await res.json();

                if (data.success) {
                    bookData = data.book;
                    currentBookId = bookId;
                    document.getElementById('reader-title').textContent = bookData.book;

                    // R9: 渲染顶部"关于此书"卡
                    renderBookInfoCard(bookData);

                    // R9: 渲染左侧真 TOC 侧边栏 (用真 toc 优先, 降级到 chapter 列表)
                    renderTocSidebar(bookData);

                    flattenBook(bookData);
                    await applyReadingDensity();
                    selectChapter(0);
                    showReader();
                    calculateAR();
                }
            } catch (err) {
                console.error('Failed to load book:', err);
            }
        }

        // R9/R24: 渲染目录 (现在在抽屉里) — 用真 toc, 没有时降级到 chapter 列表
        function renderTocSidebar(book) {
            const list = document.getElementById('toc-list');
            list.innerHTML = '';
            const toc = book.toc || [];
            const chapters = book.chapters || [];

            // 优先用真 toc
            if (toc.length > 0) {
                toc.forEach((entry, i) => {
                    const btn = document.createElement('button');
                    btn.className = 'toc-item' + (i === 0 ? ' active' : '');
                    btn.innerHTML = `<div>${entry.title}</div><div class="toc-item-meta">第 ${i + 1} 章</div>`;
                    btn.onclick = () => {
                        // 真 toc 的 href 跟 chapters 数组里没严格对应, 但顺序一般对得上
                        // 找不到匹配的 chapter 时, fall back 到第 i 个
                        const idx = Math.min(i, chapters.length - 1);
                        // R10: toc 项数远大于 chapter 数(扫描版/无 h1 的书)时,
                        // 所有点击都落到 chapter 0, 视觉上"没用"。给个提示告诉家长真相。
                        if (toc.length > chapters.length * 2) {
                            showToast('此书未识别章节边界,目录仅供参考');
                            return;
                        }
                        selectChapter(idx);
                    };
                    list.appendChild(btn);
                });
                // 章节边界未识别时, 在 list 底部再放一次提示
                if (toc.length > chapters.length * 2) {
                    list.insertAdjacentHTML('beforeend',
                        '<div class="toc-empty">⚠️ 此书未识别章节边界,目录仅供参考</div>');
                }
            } else if (chapters.length > 0) {
                // 降级: 用 chapter.name 当目录项
                chapters.forEach((ch, i) => {
                    const btn = document.createElement('button');
                    btn.className = 'toc-item' + (i === 0 ? ' active' : '');
                    btn.textContent = ch.name || `第 ${i + 1} 章`;
                    btn.onclick = () => selectChapter(i);
                    list.appendChild(btn);
                });
            } else {
                list.innerHTML = '<div class="toc-empty">无目录信息</div>';
            }
        }

        // R9: 渲染顶部"关于此书"卡 — 封面 + 标题 + 作者/出版/年份 + 简介 (可展开)
        function renderBookInfoCard(book) {
            const card = document.getElementById('book-info-card');
            card.style.display = 'flex';

            // 封面 (有本地 cover 用本地, 没有显示 fallback 色块)
            const coverSlot = document.getElementById('book-info-cover-slot');
            if (book.cover) {
                const safeTitle = (book.book || '').replace(/'/g, '&#39;');
                coverSlot.innerHTML = `<img class="book-info-cover" src="${book.cover}" alt="${(book.book || '').replace(/"/g, '&quot;')}">`;
                const img = coverSlot.querySelector('.book-info-cover');
                if (img) img.addEventListener('error', () => {
                    img.outerHTML = `<div class="book-info-cover-fallback">${safeTitle}</div>`;
                });
            } else {
                coverSlot.innerHTML = `<div class="book-info-cover-fallback">${book.book || ''}</div>`;
            }

            // 标题
            document.getElementById('book-info-title').textContent = book.book || '';

            // meta 行: 作者 · 出版 · 年份 · 语言 · 标识符
            const meta = document.getElementById('book-info-meta');
            const parts = [];
            if (book.creator) parts.push(`<span>👤 ${book.creator}</span>`);
            if (book.publisher) parts.push(`<span>📚 ${book.publisher}</span>`);
            if (book.year) parts.push(`<span>📅 ${book.year}</span>`);
            if (book.language) parts.push(`<span>🌐 ${book.language}</span>`);
            if (book.identifier) parts.push(`<span>🆔 ${book.identifier}</span>`);
            meta.innerHTML = parts.join('') || '<span>无出版信息</span>';

            // 简介 (有描述才显示)
            const desc = document.getElementById('book-info-description');
            const toggle = document.getElementById('book-info-toggle');
            if (book.description) {
                desc.textContent = book.description;
                desc.classList.remove('expanded');
                desc.classList.add('collapsed');
                // 内容超 4.8em 时显示 "展开"
                if (desc.scrollHeight > desc.clientHeight + 4) {
                    toggle.style.display = 'inline';
                    toggle.textContent = '展开 ↓';
                    toggle.onclick = () => {
                        const expanded = desc.classList.toggle('expanded');
                        desc.classList.toggle('collapsed', !expanded);
                        toggle.textContent = expanded ? '收起 ↑' : '展开 ↓';
                    };
                } else {
                    toggle.style.display = 'none';
                }
            } else {
                desc.textContent = '';
                toggle.style.display = 'none';
            }
        }

        // 把全书各章拍平成一条句子流。
        // 原来 sentences 只装当前一章,于是 nextPage 到本章末屏就夹住不动,
        // 「下一页」按钮变灰 —— 读完整本书得靠一次次手动点目录换章。
        // 16 章的书读起来像 16 本 12 页的小册子,自然被当成「书被截断了」。
        function flattenBook(book) {
            const chs = (book && book.chapters) || [];
            const all = [];
            const starts = [];
            chs.forEach((ch) => {
                starts.push(all.length);
                const s = (ch && ch.sentences) || [];
                for (let k = 0; k < s.length; k++) all.push(s[k]);
            });
            sentences = all;
            chapterStarts = starts;
        }

        // 句子下标 → 所属章。空章的 start 与下一章相同,这里取到的是后面那章,
        // 免得游标停在空章上、章名一片空白。
        function chapterIndexOf(idx) {
            let ci = 0;
            for (let i = 0; i < chapterStarts.length; i++) {
                if (chapterStarts[i] <= idx) ci = i; else break;
            }
            return ci;
        }

        // 读孩子档案。每次打开一本书都拉一次 —— 一次小请求而已,
        // 但换来的是「家长刚改完档案,孩子下一本书立刻生效」。
        // 之前做成一会话只拉一次,结果家长改完档案孩子这边纹丝不动。
        async function fetchChildProfile() {
            try {
                const res = await fetch('/api/child/profile');
                const data = await res.json();
                if (data && data.success && data.child) childProfile = data.child;
            } catch (e) {
                // 拉不到档案不该挡住读书,退回默认值继续
            }
            return childProfile;
        }

        // 按「书的难度 - 孩子的水平」定每屏句数。
        // gap = book - child:负数说明书比孩子简单,孩子读得轻松就该少打断;
        // 正数说明书偏难,拆细、留白,否则满屏字看着就发怵。
        function computeDensity(bookLexile, childLexile) {
            // 注意:Number(null) 和 Number('') 都是 0,不是 NaN。
            // 只判 Number.isFinite 的话,「没填蓝思值」会被当成 0 分处理,
            // gap 变成整本书的难度,直接把密度压到最低档。必须先挡掉空值。
            const num = (v, fallback) => {
                if (v === null || v === undefined || v === '') return fallback;
                const n = Number(v);
                return Number.isFinite(n) ? n : fallback;
            };
            const bl = num(bookLexile, 500);
            let cl = num(childLexile, DEFAULT_CHILD_LEXILE);
            cl = Math.max(0, Math.min(cl, 2000));
            const gap = bl - cl;
            for (const [upper, perPage, mode] of READING_DENSITY_STEPS) {
                if (upper === null || gap <= upper) {
                    return { sentencesPerPage: perPage, mode, gap,
                             bookLexile: bl, childLexile: cl };
                }
            }
            return { sentencesPerPage: 3, mode: 'focus', gap,
                     bookLexile: bl, childLexile: cl };
        }

        async function applyReadingDensity() {
            await fetchChildProfile();
            const d = computeDensity(bookData && bookData.lexile, childProfile.lexile);
            sentencesPerPage = d.sentencesPerPage;
            readingMode = d.mode;
            // 形态切换靠 reader-page 上的 class,两种样式在 CSS 里各写一套。
            const page = document.getElementById('reader-page');
            if (page) page.classList.toggle('mode-book', d.mode === 'book');
            updateDensityHint(d);
            return d;
        }

        // 把「为什么这一屏是几句」讲清楚,不然家长看到 10 句会以为坏了。
        function updateDensityHint(d) {
            const el = document.getElementById('density-hint');
            if (!el) return;
            const who = childProfile.name ? childProfile.name : '孩子';
            if (d.childLexile === DEFAULT_CHILD_LEXILE && childProfile.lexile == null) {
                el.textContent = `每页 ${d.sentencesPerPage} 句 · 还没设置孩子水平,按默认估的`;
                el.title = '在家长页填「孩子档案」后,每页句数会按书的难度自动变';
                return;
            }
            el.textContent = `每页 ${d.sentencesPerPage} 句 · ${who} ${d.childLexile}L / 本书 ${d.bookLexile}L`;
            el.title = d.gap < 0
                ? '这本书比孩子的水平简单,所以一页多给一些'
                : (d.gap > 0 ? '这本书比孩子的水平难,所以拆细一些' : '难度和孩子正好匹配');
        }

        // 目录高亮 + 上一章/下一章按钮的可用态。
        // 翻页现在会跨章,所以这活儿不能只挂在 selectChapter 上 ——
        // 必须每次重绘都重算,否则读到下一章首句时章名还停在上一章。
        function updateChapterChrome() {
            currentChapterIndex = chapterIndexOf(currentSentenceIndex);
            document.querySelectorAll('.toc-item').forEach((item, i) => {
                item.className = item.className.replace(/\s*active/g, '');
                if (i === currentChapterIndex) item.className += ' active';
            });
            const last = (bookData && bookData.chapters ? bookData.chapters.length : 1) - 1;
            document.querySelectorAll('[data-action="prevChapter"]')
                .forEach(b => b.disabled = currentChapterIndex === 0);
            document.querySelectorAll('[data-action="nextChapter"]')
                .forEach(b => b.disabled = currentChapterIndex >= last);
        }

        // 选择章节
        function selectChapter(index) {
            if (!chapterStarts.length) return;
            const ci = Math.max(0, Math.min(parseInt(index, 10) || 0,
                                            chapterStarts.length - 1));
            currentChapterIndex = ci;
            currentSentenceIndex = chapterStarts[ci];

            updateDisplay();
            clearTranslation();
        }

        // 上一章
        function prevChapter() {
            if (currentChapterIndex > 0) {
                selectChapter(currentChapterIndex - 1);
            }
        }

        // 下一章
        function nextChapter() {
            if (currentChapterIndex < bookData.chapters.length - 1) {
                selectChapter(currentChapterIndex + 1);
            }
        }

        // 跳转到句子
        function jumpTo(index) {
            currentSentenceIndex = index;
            updateDisplay();
            translateSentence(sentences[index]);
            scrollToCurrentSentence();
            playCurrentSentence();
        }

        // ========== 整屏翻页(底栏按钮) ==========
        // 这两个只给底栏的「上一页 / 下一页」按钮用,方向键不走这里 ——
        // 方向键是一句一句挪的(见 keydown 那段)。两者分工:
        //   方向键 → 上下句,走到本页最后一句时页面自然翻过去
        //   按钮   → 一次跳一整屏,快速略过
        // 加这两个按钮的起因:一屏只放几句,而 prevSentence/nextSentence 一次只 +1,
        // 连按好几次才看到换页,而且界面上没有任何翻页入口,完全无从发现。
        function prevPage() {
            if (!sentences || !sentences.length) return;
            currentSentenceIndex = Math.max(0, currentSentenceIndex - sentencesPerPage);
            updateDisplay();
        }

        function nextPage() {
            if (!sentences || !sentences.length) return;
            // 末屏不满 sentencesPerPage 句,直接落到最后一句所在屏
            const maxStart = Math.max(0, Math.ceil(sentences.length / sentencesPerPage) - 1);
            const target = pageStartIndex(currentSentenceIndex) + sentencesPerPage;
            currentSentenceIndex = Math.min(target, maxStart * sentencesPerPage);
            currentSentenceIndex = Math.min(currentSentenceIndex, sentences.length - 1);
            updateDisplay();
        }

        // 首屏/末屏时把翻页按钮置灰,和上一章/下一章的处理保持一致
        function updatePageButtons() {
            const total = sentences ? sentences.length : 0;
            const per = sentencesPerPage;
            const page = total ? Math.floor(currentSentenceIndex / per) : 0;
            const lastPage = total ? Math.max(0, Math.ceil(total / per) - 1) : 0;
            document.querySelectorAll('[data-action="prevPage"]')
                .forEach(b => b.disabled = page <= 0);
            document.querySelectorAll('[data-action="nextPage"]')
                .forEach(b => b.disabled = page >= lastPage);
        }

        // 导航
        function prevSentence() {
            if (currentSentenceIndex > 0) {
                currentSentenceIndex--;
                updateDisplay();
                translateSentence(sentences[currentSentenceIndex]);
                scrollToCurrentSentence();
            }
        }

        function nextSentence() {
            if (currentSentenceIndex < sentences.length - 1) {
                currentSentenceIndex++;
                updateDisplay();
                translateSentence(sentences[currentSentenceIndex]);
                scrollToCurrentSentence();
            }
        }

        // 翻译句子
        async function translateSentence(sentence) {
            const el = document.getElementById('translation-content');
            if (el) el.innerHTML = '<div class="translation-loading">翻译中...</div>';

            // R10: sidebar 折叠时用户看不到 translation-content, 同时弹 toast
            showToast('翻译中...', 1500);

            try {
                const res = await fetch(
                    `https://api.mymemory.translated.net/get?q=${encodeURIComponent(sentence)}&langpair=en|zh-CN`
                );
                const data = await res.json();

                if (data.responseStatus === 200 && data.responseData?.translatedText) {
                    const text = data.responseData.translatedText;
                    if (el) el.innerHTML = `<div class="sentence-translation-text">${text}</div>`;
                    showToast(text, 5000);  // 弹 5s, 折叠 sidebar 也能看到
                } else {
                    if (el) el.innerHTML = '<div class="translation-content">翻译失败</div>';
                    showToast('翻译失败: API 未返回结果', 3000);
                }
            } catch (err) {
                if (el) el.innerHTML = '<div class="translation-content">翻译失败</div>';
                showToast('翻译失败: 网络错误', 3000);
            }
        }

        function clearTranslation() {
            document.getElementById('translation-content').innerHTML = '点击上方句子，查看翻译';
        }

        // 查词
        async function lookupWord(word, element, event) {
            event.stopPropagation();
            const cleanWord = word.replace(/[^a-zA-Z]/g, '').toLowerCase();
            if (!cleanWord) return;

            currentWord = cleanWord;

            // 如果已经标记过，则取消标记
            if (lookedWords[cleanWord]) {
                element.classList.remove('looked');
                delete lookedWords[cleanWord];
                localStorage.setItem('lookedWords', JSON.stringify(lookedWords));
                shadowReport({ vocabulary: { lookedWords } });
                return;
            }

            // 标记为已查
            element.classList.add('looked');
            lookedWords[cleanWord] = true;
            localStorage.setItem('lookedWords', JSON.stringify(lookedWords));
            shadowReport({ vocabulary: { lookedWords } });

            const modal = document.getElementById('word-modal');
            document.getElementById('modal-word').textContent = cleanWord;
            document.getElementById('modal-phonetic').textContent = '加载中...';
            document.getElementById('modal-meanings').innerHTML = '<div class="translation-loading">查询中...</div>';
            modal.classList.add('show');

            // 更新生词本按钮状态
            const vocabBtn = document.getElementById('btn-add-vocab');
            vocabBtn.textContent = vocabulary.find(v => v.word === cleanWord) ? '✓ 已收录' : '+ 生词本';
            vocabBtn.disabled = !!vocabulary.find(v => v.word === cleanWord);

            try {
                // 走自家后端而不是直连词典站(2026-09-30)。前端直连
                // api.dictionaryapi.dev 在国内 100% 连不上,查词按钮等于坏的;
                // 挪到服务端后由后端选上游 + 缓存,平板换网络也不影响。
                const res = await fetch(`/api/dict/${encodeURIComponent(cleanWord)}`);
                const data = await res.json().catch(() => null);

                if (data && data.success) {
                    document.getElementById('modal-phonetic').textContent =
                        data.phonetic ? `/${data.phonetic}/` : '';

                    const meanings = data.meanings || [];
                    document.getElementById('modal-meanings').innerHTML = meanings.length
                        ? meanings.map(m => `
                            <div class="word-meaning-item">
                                ${m.part ? `<div class="word-meaning-part">${escapeHtml(m.part)}</div>` : ''}
                                <div class="word-meaning-cn">${escapeHtml(m.cn)}</div>
                            </div>`).join('')
                        : '<div>没查到这个词</div>';
                } else if (data && data.retryable) {
                    // 词典连不上 ≠ 查无此词,两回事,别混成一句「查询失败」
                    document.getElementById('modal-phonetic').textContent = '';
                    document.getElementById('modal-meanings').innerHTML =
                        '<div>词典暂时连不上,检查一下网络再点一次</div>';
                } else {
                    document.getElementById('modal-phonetic').textContent = '';
                    document.getElementById('modal-meanings').innerHTML =
                        `<div>${escapeHtml(data?.error || '没查到这个词')}</div>`;
                }
            } catch (err) {
                document.getElementById('modal-phonetic').textContent = '';
                document.getElementById('modal-meanings').innerHTML = '<div>查询失败,检查一下网络</div>';
            }
        }

        function closeWordModal() {
            document.getElementById('word-modal').classList.remove('show');
        }

        // 发音 (使用微软edge-tts)
        function playPronunciation() {
            if (!currentWord) return;

            // 优先使用微软edge-tts
            fetch('/api/tts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: currentWord, voice: currentVoice })
            }).then(res => res.json()).then(data => {
                if (data.success) new Audio(data.audio_url).play();
            }).catch(err => {
                // 降级使用浏览器TTS
                if ('speechSynthesis' in window) {
                    speechSynthesis.cancel();
                    const utterance = new SpeechSynthesisUtterance(currentWord);
                    utterance.lang = 'en-US';
                    utterance.rate = 0.9;
                    speechSynthesis.speak(utterance);
                }
            });
        }

        // 生词本
        function addToVocab() {
            if (!currentWord) return;
            if (vocabulary.find(v => v.word === currentWord)) return;

            const meaningEl = document.getElementById('modal-meanings');
            const parts = meaningEl.querySelectorAll('.word-meaning-part');
            const defs = meaningEl.querySelectorAll('.word-meaning-def');

            let meaning = '';
            parts.forEach((p, i) => {
                if (defs[i]) meaning += `${p.textContent}: ${defs[i].textContent}; `;
            });

            // 艾宾浩斯：明天复习
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);

            vocabulary.push({
                word: currentWord,
                meaning: meaning || '未找到释义',
                book: bookData?.book || 'Unknown',
                chapter: bookData?.chapters[currentChapterIndex]?.name || 'Unknown',
                date: new Date().toLocaleDateString(),
                nextReview: tomorrow.toISOString().split('T')[0],
                level: 0
            });

            localStorage.setItem('vocabulary', JSON.stringify(vocabulary));
            shadowReport({ vocabulary: { newWords: vocabulary } });
            updateVocabCount();
            renderVocabList();
            updateReviewReminder();
            updateStats({ wordsLearned: 1 });

            const vocabBtn = document.getElementById('btn-add-vocab');
            vocabBtn.textContent = '✓ 已收录';
            vocabBtn.disabled = true;
        }

        function updateVocabCount() {
            document.getElementById('vocab-count').textContent = `(${vocabulary.length})`;
        }

        function renderVocabList() {
            const list = document.getElementById('vocab-list');
            if (vocabulary.length === 0) {
                list.innerHTML = '<div class="vocab-empty">点击单词加入生词本</div>';
                return;
            }
            list.innerHTML = vocabulary.slice(-10).reverse().map(v => {
                const m = escapeHtml((v.meaning || '').substring(0, 50)) + (v.meaning && v.meaning.length > 50 ? '...' : '');
                return `
                <div class="vocab-item">
                    <div class="vocab-word">${escapeHtml(v.word)}</div>
                    <div class="vocab-meaning">${m}</div>
                </div>
            `;}).join('');
        }

        // ========== 艾宾浩斯复习系统 ==========

        // 获取需要复习的单词
        function getWordsForReview() {
            const today = new Date().toISOString().split('T')[0];
            return vocabulary.filter(v => {
                // 没有复习日期的单词需要复习
                if (!v.nextReview) return true;
                // 复习日期 <= 今天需要复习
                if (v.nextReview <= today) return true;
                return false;
            });
        }

        // 更新复习提醒
        function updateReviewReminder() {
            const toReview = getWordsForReview();
            const badge = document.getElementById('review-badge');
            const count = document.getElementById('review-count');
            const btn = document.getElementById('btn-start-review');

            if (toReview.length > 0) {
                badge.classList.remove('hidden');
                count.textContent = toReview.length;
                btn.style.display = 'block';
            } else {
                badge.classList.add('hidden');
                btn.style.display = 'none';
            }
        }

        // 开始复习
        function startReview() {
            reviewQueue = getWordsForReview();
            if (reviewQueue.length === 0) {
                alert('暂无需要复习的单词！');
                return;
            }
            currentReviewIndex = 0;
            reviewCorrect = 0;
            reviewWrong = 0;
            showReviewCard();
            document.getElementById('review-modal').classList.add('show');
        }

        // 显示复习卡片
        function showReviewCard() {
            if (currentReviewIndex >= reviewQueue.length) {
                showReviewDone();
                return;
            }

            const word = reviewQueue[currentReviewIndex];
            const content = document.getElementById('review-content');
            content.innerHTML = `
                <div class="review-progress">${currentReviewIndex + 1} / ${reviewQueue.length}</div>
                <div class="review-word">${escapeHtml(word.word)}</div>
                <div class="review-meaning">${escapeHtml(word.meaning)}</div>
                <div class="review-buttons">
                    <button class="review-btn wrong" data-action="reviewAnswer" data-arg="false">不认识</button>
                    <button class="review-btn correct" data-action="reviewAnswer" data-arg="true">认识 ✓</button>
                </div>
            `;
        }

        // 复习答题
        function reviewAnswer(correct) {
            const word = reviewQueue[currentReviewIndex];

            if (correct) {
                reviewCorrect++;
                // 答对了，提升复习间隔
                word.level = (word.level || 0) + 1;
                const intervalIndex = Math.min(word.level, REVIEW_INTERVALS.length - 1);
                const days = REVIEW_INTERVALS[intervalIndex];
                const next = new Date();
                next.setDate(next.getDate() + days);
                word.nextReview = next.toISOString().split('T')[0];
            } else {
                reviewWrong++;
                // 答错了，重置间隔
                word.level = 0;
                const next = new Date();
                next.setDate(next.getDate() + 1);
                word.nextReview = next.toISOString().split('T')[0];
            }

            // 保存到 localStorage
            localStorage.setItem('vocabulary', JSON.stringify(vocabulary));
            shadowReport({ vocabulary: { newWords: vocabulary } });

            currentReviewIndex++;
            setTimeout(showReviewCard, 300);
        }

        // 复习完成
        function showReviewDone() {
            const content = document.getElementById('review-content');
            const accuracy = reviewQueue.length > 0 ? Math.round((reviewCorrect / reviewQueue.length) * 100) : 0;

            content.innerHTML = `
                <div class="review-done">
                    <div class="review-done-icon">${accuracy >= 80 ? '🎉' : accuracy >= 50 ? '👍' : '💪'}</div>
                    <h3>${accuracy >= 80 ? '太棒了！' : accuracy >= 50 ? '不错！' : '继续加油！'}</h3>
                    <p class="done-sub">本次复习完成</p>
                    <div class="review-stats">
                        <div class="review-stat">
                            <div class="review-stat-value correct">${reviewCorrect}</div>
                            <div>认识</div>
                        </div>
                        <div class="review-stat">
                            <div class="review-stat-value wrong">${reviewWrong}</div>
                            <div>不认识</div>
                        </div>
                    </div>
                    <p class="done-sub">正确率: ${accuracy}%</p>
                    <button class="btn btn-primary done-btn" data-action="closeReviewModal">完成</button>
                </div>
            `;

            // 更新统计
            updateStats({ wordsMastered: reviewCorrect });
            updateReviewReminder();
        }

        // 关闭复习弹窗
        function closeReviewModal() {
            document.getElementById('review-modal').classList.remove('show');
            updateReviewReminder();
            renderVocabList();
        }

        // AR 计算
        function calculateAR() {
            if (!bookData) return;

            let totalWords = 0, totalSentences = 0, uniqueWords = new Set(), totalSyllables = 0;

            bookData.chapters.forEach(ch => {
                ch.sentences.forEach(sent => {
                    const words = sent.split(/\s+/).filter(w => /^[a-zA-Z]+$/.test(w));
                    totalWords += words.length;
                    totalSentences++;
                    words.forEach(w => {
                        uniqueWords.add(w.toLowerCase());
                        totalSyllables += countSyllables(w);
                    });
                });
            });

            const avgWordLength = totalWords > 0 ? (totalSyllables / totalWords) : 0;
            const avgSentenceLength = totalSentences > 0 ? (totalWords / totalSentences) : 0;
            const ar = 4.86 + (0.12 * avgSentenceLength) + (0.05 * avgWordLength);

            document.getElementById('ar-display').textContent = ar.toFixed(1);
            document.getElementById('ar-words').textContent = totalWords;
            document.getElementById('ar-sentences').textContent = totalSentences;
        }

        function countSyllables(word) {
            word = word.toLowerCase();
            if (word.length <= 3) return 1;
            word = word.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, '');
            word = word.replace(/^y/, '');
            const matches = word.match(/[aeiouy]{1,2}/g);
            return matches ? matches.length : 1;
        }

        function showARPanel() {
            if (!bookData) return;
            calculateAR();
            document.getElementById('modal-ar-value').textContent = document.getElementById('ar-display').textContent;
            document.getElementById('modal-ar-words').textContent = document.getElementById('ar-words').textContent;
            document.getElementById('modal-ar-sentences').textContent = document.getElementById('ar-sentences').textContent;

            let totalWords = 0, totalSentences = 0, uniqueWords = new Set(), totalSyllables = 0;
            bookData.chapters.forEach(ch => {
                ch.sentences.forEach(sent => {
                    const words = sent.split(/\s+/).filter(w => /^[a-zA-Z]+$/.test(w));
                    totalWords += words.length;
                    totalSentences++;
                    words.forEach(w => {
                        uniqueWords.add(w.toLowerCase());
                        totalSyllables += countSyllables(w);
                    });
                });
            });
            document.getElementById('modal-ar-unique').textContent = uniqueWords.size;
            document.getElementById('modal-ar-avg').textContent = (totalWords > 0 ? (totalSyllables / totalWords) : 0).toFixed(1);

            document.getElementById('ar-modal').classList.add('show');
        }

        function closeARPanel() {
            document.getElementById('ar-modal').classList.remove('show');
        }

        // TTS 播放 (优先使用微软edge-tts，备用浏览器TTS)
        // 使用Web Speech API播放并缓存
        async function playWithCache(text, onEnd) {
            const btn = document.getElementById('btn-play');
            const status = document.getElementById('status-playing');

            // 防双击叠音: 每次调用都生成一个 token, await 后只接受最新的
            const myToken = ++ttsRequestSeq;

            // 1. 优先从缓存读取
            const cachedAudio = await audioCache.getAudio(currentBookId, currentSentenceIndex, text);
            if (myToken !== ttsRequestSeq) return;  // 已被新调用覆盖, 丢弃
            if (cachedAudio) {
                if (audioElement) audioElement.pause();
                if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
                currentAudioUrl = URL.createObjectURL(cachedAudio);
                audioElement = new Audio(currentAudioUrl);
                isPlaying = true;

                audioElement.onended = () => {
                    isPlaying = false;
                    btn.disabled = false;
                    btn.classList.remove('playing');
                    setReadAloudLabel(false);
                    status.classList.add('hidden');
                    if (onEnd) onEnd();
                    // 自动缓存下一句
                    cacheNextSentence();
                };
                audioElement.onerror = () => {
                    // 缓存失效，使用Web Speech API
                    playWithWebSpeech(text, onEnd);
                };
                audioElement.play();
                return;
            }

            // 2. 缓存没有，使用Web Speech API
            playWithWebSpeech(text, onEnd);
        }

        // 使用Web Speech API播放
        function playWithWebSpeech(text, onEnd) {
            const btn = document.getElementById('btn-play');
            const status = document.getElementById('status-playing');

            if (!('speechSynthesis' in window)) {
                btn.disabled = false;
                    btn.classList.remove('playing');
                    setReadAloudLabel(false);
                status.classList.add('hidden');
                return;
            }

            speechSynthesis.cancel();

            // 等待音色加载
            const voices = speechSynthesis.getVoices();
            const voice = voices.find(v => v.lang.startsWith('en')) || voices[0];

            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'en-US';
            utterance.rate = 0.9;
            utterance.voice = voice;

            utterance.onend = () => {
                isPlaying = false;
                btn.disabled = false;
                    btn.classList.remove('playing');
                    setReadAloudLabel(false);
                status.classList.add('hidden');
                if (onEnd) onEnd();
                // 缓存这句
                cacheCurrentSentence();
                // 自动缓存下一句
                cacheNextSentence();
            };

            utterance.onerror = () => {
                isPlaying = false;
                btn.disabled = false;
                    btn.classList.remove('playing');
                    setReadAloudLabel(false);
                status.classList.add('hidden');
            };

            speechSynthesis.speak(utterance);
            isPlaying = true;
        }

        function setReadAloudLabel(playing) {
            const icon = document.getElementById('play-icon');
            const label = document.querySelector('.read-aloud-text');
            if (icon) icon.textContent = playing ? '⏸' : '🔊';
            if (label) label.textContent = playing ? '停止' : '朗读';
        }

        async function playCurrentSentence() {
            if (!sentences || sentences.length === 0) return;

            const text = sentences[currentSentenceIndex];
            const btn = document.getElementById('btn-play');
            const status = document.getElementById('status-playing');

            btn.disabled = true;
            btn.classList.add('playing');
            setReadAloudLabel(true);
            status.classList.remove('hidden');

            // 滚动到当前句子
            scrollToCurrentSentence();

            await playWithCache(text);
        }

        // 缓存当前句子
        async function cacheCurrentSentence() {
            if (!sentences || !currentBookId) return;
            const text = sentences[currentSentenceIndex];
            if (!text || text.length > 500) return;

            // 检查是否已缓存
            const existing = await audioCache.getAudio(currentBookId, currentSentenceIndex, text);
            if (existing) return;

            // 使用Web Speech API生成音频并缓存
            if ('speechSynthesis' in window) {
                const voices = speechSynthesis.getVoices();
                const voice = voices.find(v => v.lang.startsWith('en')) || voices[0];

                // 创建MediaStreamDestination来录制
                const utterance = new SpeechSynthesisUtterance(text);
                utterance.lang = 'en-US';
                utterance.rate = 0.9;
                utterance.voice = voice;

                // 由于Web Speech API不提供音频数据，我们使用服务器TTS
                try {
                    const res = await fetch('/api/tts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text, voice: currentVoice })
                    });
                    const data = await res.json();
                    if (data.success && data.audio_url) {
                        // 下载音频并保存到IndexedDB
                        const audioRes = await fetch(data.audio_url);
                        const audioBlob = await audioRes.blob();
                        await audioCache.saveAudio(currentBookId, currentSentenceIndex, text, audioBlob);
                        updateCacheProgressUI();
                    }
                } catch (e) {
                    console.log('Cache failed:', e);
                }
            }
        }

        // 缓存下一句（后台）
        async function cacheNextSentence() {
            if (!sentences || !currentBookId) return;
            const nextIndex = currentSentenceIndex + 1;
            if (nextIndex >= sentences.length) return;

            const text = sentences[nextIndex];
            if (!text || text.length > 500) return;

            // 检查是否已缓存
            const existing = await audioCache.getAudio(currentBookId, nextIndex, text);
            if (existing) return;

            // 后台缓存下一句
            setTimeout(async () => {
                try {
                    const res = await fetch('/api/tts', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text, voice: currentVoice })
                    });
                    const data = await res.json();
                    if (data.success && data.audio_url) {
                        const audioRes = await fetch(data.audio_url);
                        const audioBlob = await audioRes.blob();
                        await audioCache.saveAudio(currentBookId, nextIndex, text, audioBlob);
                        updateCacheProgressUI();
                    }
                } catch (e) {}
            }, 100);
        }

        // 更新缓存进度UI
        async function updateCacheProgressUI() {
            if (!currentBookId) return;
            const progress = await audioCache.getBookProgress(currentBookId);
            const badge = document.getElementById(`cache-badge-${currentBookId}`);
            if (badge && progress.total > 0) {
                badge.textContent = `🔊 ${progress.cached}/${progress.total}`;
                badge.style.display = progress.cached > 0 ? 'inline-block' : 'none';
            }
        }

        // 导入书籍 - 绑定文件输入
        document.getElementById('import-file').addEventListener('change', (e) => importBook(e.target.files[0]));

        async function importBook(file) {
            if (!file || !file.name.endsWith('.epub')) {
                alert('请选择 EPUB 格式文件');
                return;
            }

            const formData = new FormData();
            formData.append('epub', file);

            // R22: 导入三段式(选文件 → 导入中 → 解析完成),照设计稿 C。
            // 成功不用 alert —— 弹窗会打断阅读,孩子看到的应该是新书自己出现在架子上。
            const importCard = document.querySelector('.import-card');
            if (importCard) {
                importCard.querySelector('.text').textContent = '导入中…';
                importCard.querySelector('.hint').textContent = file.name;
            }

            try {
                const res = await fetch('/api/book/import', { method: 'POST', body: formData });
                const data = await res.json();

                if (data.success) {
                    loadBookList();
                } else if (res.status === 401) {
                    // R10: 之前 401 之后只 alert "未授权", 家长不知道去哪儿登录
                    if (confirm('导入需要家长登录。\n\n是否现在跳转到登录页? (默认 PIN: 0000)')) {
                        window.location.href = '/parent';
                    }
                    loadBookList();
                } else if (res.status === 409) {
                    alert('导入失败 (重复):\n\n' + data.error + '\n\n建议: 重命名文件后重试, 或先去 /parent 删除旧书');
                    loadBookList();
                } else {
                    alert('导入失败: ' + (data.error || `HTTP ${res.status}`));
                    loadBookList();
                }
            } catch (err) {
                alert('导入失败 (网络错误)');
                loadBookList();
            }
        }

        // 删除书籍
        async function deleteBook(bookId, bookTitle) {
            if (!confirm(`确定删除《${bookTitle}》？`)) return;

            try {
                await fetch(`/api/book/${bookId}`, { method: 'DELETE' });
                loadBookList();
            } catch (err) {
                alert('删除失败');
            }
        }

        // R24: 初版是「一屏只放 3 句」,设计稿的阅读区是「当前页的大字号英文」。
        // 2026-09-30 改成动态:由「书的蓝思值 - 孩子的蓝思值」决定,见 applyReadingDensity。
        // focus = 3~5 句大字号聚焦(初级);book = 7~10 句连续小字(高段位)。

        // 当前页的第一句在全书里的下标。
        // 用整除而不是「从当前句起往后取」:后者每翻一句整屏文字都会往上挪,
        // 眼睛要重新找位置;整除让文字只在翻页时才动。
        function pageStartIndex(current) {
            return Math.floor(current / sentencesPerPage) * sentencesPerPage;
        }

        function updateDisplay() {
            // 翻页会跨章,当前章必须先按游标重算,章名/目录高亮才对得上
            updateChapterChrome();
            const container = document.getElementById('sentence-display');
            const start = pageStartIndex(currentSentenceIndex);
            let html = '';
            for (let i = start; i < Math.min(start + sentencesPerPage, sentences.length); i++) {
                html += formatSentence(sentences[i], i);
            }
            container.innerHTML = html;

            // 更新进度。顶栏右侧 N / M 就是「孩子第一眼要知道读到哪了」。
            const total = sentences.length;
            const current = currentSentenceIndex + 1;
            const percent = total > 0 ? Math.round((currentSentenceIndex / total) * 100) : 0;
            document.getElementById('progress-fill').style.width = percent + '%';
            document.getElementById('reader-pos').textContent = `${current} / ${total}`;
            const chEl = document.getElementById('reader-chapter');
            if (chEl) {
                const ch = (bookData && bookData.chapters || [])[currentChapterIndex];
                chEl.textContent = ch ? (ch.name || ch.title || '') : '';
            }
            updatePageButtons();
            scheduleProgressSave();
        }

        // R22: 上报阅读位置。书架页的「继续读」卡片靠这个数据,
        // 之前只有跟读页在写,主阅读器不写,书架永远显示「未开始」。
        // 翻句很频繁 → debounce,静默失败不打断阅读。
        let _progressSaveTimer = null;
        function scheduleProgressSave() {
            if (!currentBookId) return;
            clearTimeout(_progressSaveTimer);
            _progressSaveTimer = setTimeout(saveProgress, 800);
        }

        async function saveProgress() {
            if (!currentBookId) return;
            try {
                // 游标现在是全书下标,但 /api/progress 的约定一直是
                // 「第几章 + 该章第几句」,书架的「继续读」卡片也按这个算百分比。
                // 这里存回章内下标,契约不变,历史进度也读得动。
                const ci = chapterIndexOf(currentSentenceIndex);
                await fetch('/api/progress', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bookId: currentBookId,
                        chapterIdx: ci,
                        sentenceIdx: currentSentenceIndex - (chapterStarts[ci] || 0),
                    }),
                });
            } catch (e) { /* 离线时静默 */ }
        }

        // 格式化句子
        function formatSentence(sent, index) {
            if (!sent) return '';
            let className = 'sentence-item';
            if (index < currentSentenceIndex) className += ' read';
            if (index === currentSentenceIndex) className += ' active';

            const words = sent.split(/(\s+)/);
            const processedWords = words.map(w => {
                if (/^[a-zA-Z][a-zA-Z'\-.,!?;:"']*$/.test(w)) {
                    const cleanW = w.replace(/[^a-zA-Z]/g, '').toLowerCase();
                    const isLooked = lookedWords[cleanW];
                    const safeW = w.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                    return `<span class="word-inline ${isLooked ? 'looked' : ''}" data-action="lookupWord" data-arg="${safeW}" >${w}</span>`;
                }
                return w;
            }).join('');

            return `<span class="${className}" id="sentence-${index}" data-action="jumpTo" data-arg="${index}">${processedWords} </span>`;
        }

        // 滚动到当前句子（朗读时）
        function scrollToCurrentSentence() {
            const activeEl = document.querySelector('.sentence-item.active');
            if (activeEl) {
                activeEl.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                    inline: 'nearest'
                });
            }
        }

        // 键盘快捷键
        // ← → 走句子,不是走整页(2026-09-30 改)。之前 ← → 直接跳一整屏,
        // 想重读上一句就得连按三次往回翻,越读越累。
        // 现在一句一句挪;由于 sentences 是全书连续的一条流,走到本页最后一句
        // 再按 →,游标越过 pageStartIndex 的边界,页面自然就翻了 —— 不用专门判断。
        // 整页翻页交给底栏那两个按钮,那里写的就是「上一页 / 下一页」。
        document.addEventListener('keydown', (e) => {
            if (document.getElementById('reader-page').classList.contains('active')) {
                if (e.key === 'ArrowLeft') {
                    prevSentence();
                }
                else if (e.key === 'ArrowRight') {
                    nextSentence();
                }
                else if (e.key === ' ' || e.key === 'Enter') {
                    e.preventDefault();
                    playCurrentSentence();
                }
                else if (e.key === 'Escape') {
                    closeWordModal();
                    closeARPanel();
                }
            }
        });

        // 窗口大小变化时重新渲染
        window.addEventListener('resize', () => {
            if (bookData && sentences.length > 0) {
                updateDisplay();
            }
        });

        // 点击弹窗外部关闭
        document.getElementById('word-modal').addEventListener('click', (e) => {
            if (e.target.id === 'word-modal') closeWordModal();
        });

        // ========== 跟读评分功能 ==========

        let audioContext = null;
        let analyser = null;
        let audioStream = null;

        // 切换阅读/跟读模式
        function setMode(mode) {
            currentMode = mode;
            document.getElementById('mode-read').classList.toggle('active', mode === 'read');
            document.getElementById('mode-shadow').classList.toggle('active', mode === 'shadow');
            document.getElementById('record-hint').textContent = mode === 'read'
                ? '阅读模式下跳过评分'
                : '点击麦克风，录音跟读';
            document.getElementById('score-display').style.display = 'none';
        }

        // 切换录音
        async function toggleRecord() {
            if (isRecording) {
                stopRecording();
            } else {
                await startRecording();
            }
        }

        // 开始录音
        async function startRecording() {
            if (!sentences || sentences.length === 0) return;

            // 检查浏览器支持
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                document.getElementById('record-hint').textContent = '❌ 浏览器不支持语音识别';
                return;
            }

            try {
                // 获取麦克风
                audioStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

                // 设置音频分析（用于可视化）
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                analyser = audioContext.createAnalyser();
                const source = audioContext.createMediaStreamSource(audioStream);
                source.connect(analyser);
                analyser.fftSize = 256;

                // 播放参考音频
                await playReferenceAudio();

            } catch (err) {
                console.error('麦克风错误:', err);
                document.getElementById('record-hint').textContent = '❌ 无法访问麦克风';
                return;
            }

            isRecording = true;
            document.getElementById('btn-record').classList.add('recording');
            document.getElementById('btn-record').textContent = '⏹';
            document.getElementById('record-hint').textContent = '🎤 正在听，请说话...';

            // 开始语音识别
            recognition = new SpeechRecognition();
            recognition.lang = 'en-US';
            recognition.continuous = true;
            recognition.interimResults = true;

            let finalTranscript = '';
            let silenceCount = 0;
            let lastResultIndex = -1;

            recognition.onresult = (event) => {
                let interimTranscript = '';
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    const transcript = event.results[i][0].transcript;
                    if (event.results[i].isFinal) {
                        finalTranscript += transcript;
                    } else {
                        interimTranscript += transcript;
                    }
                }
                // 更新提示
                if (interimTranscript) {
                    document.getElementById('record-hint').textContent = '🎤 听到: ' + interimTranscript;
                }
            };

            recognition.onerror = (event) => {
                console.error('识别错误:', event.error);
                if (event.error === 'no-speech') {
                    silenceCount++;
                    if (silenceCount > 3) {
                        document.getElementById('record-hint').textContent = '⚠️ 没听到声音，请靠近麦克风';
                    }
                } else if (event.error === 'not-allowed') {
                    document.getElementById('record-hint').textContent = '❌ 请允许麦克风权限';
                    stopRecording();
                } else if (event.error !== 'aborted') {
                    document.getElementById('record-hint').textContent = '❌ 错误: ' + event.error;
                    stopRecording();
                }
            };

            recognition.onend = () => {
                stopRecording();
                if (finalTranscript.trim()) {
                    const original = sentences[currentSentenceIndex];
                    showPronunciationScore(original, finalTranscript.trim());
                } else {
                    document.getElementById('record-hint').textContent = '⚠️ 没听清，请重试';
                }
            };

            try {
                recognition.start();
            } catch (err) {
                console.error('启动识别失败:', err);
                document.getElementById('record-hint').textContent = '❌ 无法启动识别';
                stopRecording();
            }

            // 可选：自动停止（15秒）
            setTimeout(() => {
                if (isRecording) {
                    recognition.stop();
                }
            }, 15000);
        }

        // 停止录音
        function stopRecording() {
            isRecording = false;
            document.getElementById('btn-record').classList.remove('recording');
            document.getElementById('btn-record').textContent = '🎙️';

            if (recognition) {
                try { recognition.stop(); } catch(e) {}
            }
            if (audioStream) {
                audioStream.getTracks().forEach(track => track.stop());
            }
            if (audioContext) {
                audioContext.close();
            }
        }

        // 播放参考音频
        async function playReferenceAudio() {
            if (!sentences || sentences.length === 0) return;
            try {
                const ttsRes = await fetch('/api/tts', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: sentences[currentSentenceIndex] })
                });
                const data = await ttsRes.json();
                if (data.success) {
                    const audio = new Audio(data.audio_url);
                    audio.play();
                }
            } catch (err) {
                console.error('TTS error:', err);
            }
        }

        // 显示发音评分
        function showPronunciationScore(original, transcribed) {
            const score = calculateSimilarity(original, transcribed);
            const level = getScoreLevel(score);

            document.getElementById('score-display').style.display = 'block';
            document.getElementById('score-value').textContent = score;
            document.getElementById('score-level').textContent = level.text;
            document.getElementById('score-level').className = 'score-level ' + level.class;

            // 更新圆形进度
            const degrees = (score / 100) * 360;
            document.getElementById('score-circle').style.background =
                `conic-gradient(${level.color} ${degrees}deg, var(--bg-dark) ${degrees}deg)`;

            // 显示识别结果
            document.getElementById('transcription-result').style.display = 'block';
            document.getElementById('transcription-text').textContent = transcribed;

            document.getElementById('record-hint').textContent = '点击麦克风再读一遍';
        }

        // 计算相似度
        function calculateSimilarity(original, transcribed) {
            const orig = original.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
            const trans = transcribed.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();

            if (!trans) return 0;
            if (orig === trans) return 100;

            const origWords = orig.split(/\s+/);
            const transWords = trans.split(/\s+/);

            let matchCount = 0;
            transWords.forEach(w => {
                if (origWords.includes(w)) matchCount++;
            });

            const matchRate = matchCount / transWords.length;
            const coverage = matchCount / origWords.length;
            const score = Math.round((matchRate * 0.6 + coverage * 0.4) * 100);

            return Math.min(100, score);
        }

        // 获取评分等级
        function getScoreLevel(score) {
            if (score >= 90) return { text: '🌟 非常棒！', class: 'excellent', color: '#6B8A52' };
            if (score >= 75) return { text: '👍 很棒！', class: 'great', color: '#6B8A52' };
            if (score >= 60) return { text: '📚 不错！', class: 'good', color: '#D4A574' };
            if (score >= 40) return { text: '💪 继续加油', class: 'practice', color: '#D4A574' };
            return { text: '📖 多读几遍', class: 'try', color: '#C25B56' };
        }

        // ========== 学习统计 ==========
        function updateStats(data) {
            const stats = JSON.parse(localStorage.getItem('shadowStats') || '{}');
            const today = new Date().toISOString().split('T')[0];

            // 更新每日学习时间
            if (data.studyTime) {
                stats.totalStudyTime = (stats.totalStudyTime || 0) + data.studyTime;
                stats.dailyStudyTime = stats.dailyStudyTime || {};
                stats.dailyStudyTime[today] = (stats.dailyStudyTime[today] || 0) + data.studyTime;
            }
            if (data.wordsLearned) stats.wordsLearned = (stats.wordsLearned || 0) + data.wordsLearned;
            if (data.wordsMastered) stats.wordsMastered = (stats.wordsMastered || 0) + data.wordsMastered;
            if (data.sentencesPracticed) stats.sentencesPracticed = (stats.sentencesPracticed || 0) + data.sentencesPracticed;
            if (data.chapterRead) stats.chapterRead = (stats.chapterRead || 0) + data.chapterRead;

            // 更新连续天数
            const yesterday = new Date(Date.now() - 86400000).toISOString().split('T')[0];
            if (stats.lastStudyDate === today) {
                // 今天已学习
            } else if (stats.lastStudyDate === yesterday) {
                stats.streakDays = (stats.streakDays || 0) + 1;
            } else {
                stats.streakDays = 1;
            }
            stats.lastStudyDate = today;

            localStorage.setItem('shadowStats', JSON.stringify(stats));
            shadowReport({ stats });
        }

        // ========== 阅读理解题 ==========
        // 示例阅读理解题目（实际应用中可以从后端加载）
        const comprehensionQuestions = {
            // 通用题目示例
            'default': [
                { q: "What is the main topic of this passage?", o: ["Adventure", "Cooking", "Sports", "Music"], a: 0 },
                { q: "Who are the main characters mentioned?", o: ["The author and friends", "A family", "Students and teachers", "Not clearly mentioned"], a: 3 },
                { q: "Where does the story take place?", o: ["In a city", "In a school", "Not clearly specified", "In a forest"], a: 2 },
                { q: "What happened at the end of this chapter?", o: ["A surprise", "Characters reunited", "Not enough information", "A conflict"], a: 2 },
                { q: "What can we learn from this passage?", o: ["Teamwork", "Courage", "Both are possible", "Neither"], a: 2 }
            ]
        };

        let compQuestions = [];
        let compIndex = 0;
        let compCorrect = 0;

        function showComprehensionModal() {
            const bookId = currentBookId || 'default';
            compQuestions = comprehensionQuestions[bookId] || comprehensionQuestions['default'];
            compIndex = 0;
            compCorrect = 0;
            document.getElementById('comp-modal').classList.add('show');
            showCompQuestion();
        }

        // 字体大小调节
        // 上下限按设计稿来:正文最小 24px(可读性下限),最大 40px。
        // 再小就真的读不下去了,再大一行放不下两个词。
        const FONT_MIN = 24;
        const FONT_MAX = 40;
        const FONT_DEFAULT = 28;

        function readFontSize() {
            const v = parseInt(
                getComputedStyle(document.documentElement).getPropertyValue('--sentence-font-size'), 10);
            return Number.isFinite(v) ? v : FONT_DEFAULT;
        }

        function applyFontSize(size) {
            document.documentElement.style.setProperty('--sentence-font-size', size + 'px');
        }

        function changeFontSize(delta) {
            const newSize = Math.max(FONT_MIN, Math.min(FONT_MAX, readFontSize() + delta));
            applyFontSize(newSize);
            try { localStorage.setItem('sentenceFontSize', newSize); } catch (e) {}
        }

        function initFontSize() {
            let size = FONT_DEFAULT;
            try {
                const saved = parseInt(localStorage.getItem('sentenceFontSize'), 10);
                if (Number.isFinite(saved)) size = saved;
            } catch (e) {}
            applyFontSize(Math.max(FONT_MIN, Math.min(FONT_MAX, size)));
        }

        function showCompQuestion() {
            const content = document.getElementById('comp-content');
            if (compIndex >= compQuestions.length) {
                showCompResult();
                return;
            }
            const q = compQuestions[compIndex];
            content.innerHTML = `
                <div class="comp-progress">${compIndex + 1} / ${compQuestions.length}</div>
                <div class="comp-question">${q.q}</div>
                <div class="comp-options">
                    ${q.o.map((opt, i) => `<div class="comp-option" data-action="selectCompAnswer" data-arg="${i}" data-arg2="${q.a}">${opt}</div>`).join('')}
                </div>
            `;
        }

        function selectCompAnswer(selected, correct) {
            document.querySelectorAll('.comp-option').forEach(o => o.style.pointerEvents = 'none');
            if (selected === correct) {
                document.querySelectorAll('.comp-option')[selected].classList.add('correct');
                compCorrect++;
            } else {
                document.querySelectorAll('.comp-option')[selected].classList.add('wrong');
                document.querySelectorAll('.comp-option')[correct].classList.add('correct');
            }
            setTimeout(() => {
                compIndex++;
                showCompQuestion();
            }, 1200);
        }

        function showCompResult() {
            const content = document.getElementById('comp-content');
            const total = compQuestions.length;
            const accuracy = Math.round((compCorrect / total) * 100);

            content.innerHTML = `
                <div class="comp-done">
                    <div class="comp-done-icon">${accuracy >= 80 ? '🎉' : accuracy >= 60 ? '👍' : '📚'}</div>
                    <h3>${accuracy >= 80 ? '太棒了！' : accuracy >= 60 ? '还不错！' : '继续加油！'}</h3>
                    <p class="done-sub">本章理解测验完成</p>
                    <div class="comp-stats">
                        <div class="comp-stat">
                            <div class="comp-stat-value correct">${compCorrect}</div>
                            <div>正确</div>
                        </div>
                        <div class="comp-stat">
                            <div class="comp-stat-value wrong">${total - compCorrect}</div>
                            <div>错误</div>
                        </div>
                    </div>
                    <p class="done-sub">正确率: ${accuracy}%</p>
                    <button class="btn btn-primary done-btn" data-action="closeCompModal">完成</button>
                </div>
            `;

            // 更新统计
            updateStats({ chapterRead: 1 });
        }

        function closeCompModal() {
            document.getElementById('comp-modal').classList.remove('show');
        }

        // PWA 注册
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/service-worker.js')
                .catch(err => console.log('SW registration failed:', err));
        }

        // ========== 儿童模式切换 ==========
        const kidModeToggle = document.createElement('button');
        kidModeToggle.className = 'kid-mode-toggle';
        kidModeToggle.innerHTML = '👦';
        kidModeToggle.title = '切换儿童模式';
        kidModeToggle.onclick = () => {
            document.body.classList.toggle('kid-mode');
            localStorage.setItem('kidMode', document.body.classList.contains('kid-mode'));
        };
        document.body.appendChild(kidModeToggle);

        // 恢复儿童模式状态
        if (localStorage.getItem('kidMode') === 'true') {
            document.body.classList.add('kid-mode');
        }
    