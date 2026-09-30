// 用最小 DOM stub 跑真实的 web/js/index.js,验证翻页能跨章。
// 不 stub 的话就只能靠肉眼看,而这次 bug 恰恰是「肉眼看不出来」的那类。
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const ROOT = '/Users/huangjunhai/shadow-learning';
// 自造一本 21 章 / 778 句的书,刻意复刻真实故障的形状:
// 第 0 章 14 句(真实那本的第 0 章 "Copyright" 正好 14 句),
// 于是旧代码下顶栏会显示 "1 / 14" —— 正是用户报的「只有十四页」。
const CHAPTER_SENTENCES = [14, 16, 11, 34, 44, 62, 25, 23, 74, 54, 56, 41, 46,
                           36, 37, 42, 37, 62, 44, 17, 3];
const TOTAL = CHAPTER_SENTENCES.reduce((a, b) => a + b, 0);
const book = {
  book: 'Paging Fixture', author: 'A', id: 'fixture',
  chapters: CHAPTER_SENTENCES.map((n, i) => ({
    name: `Chapter ${i}`,
    sentences: Array.from({ length: n }, (_, k) => `Sentence ${i}-${k} of the fixture book.`),
  })),
};

function mkEl(id) {
  const el = {
    id, textContent: '', innerHTML: '', value: '', hidden: false, disabled: false,
    style: {}, dataset: {}, children: [], files: [],
    className: '',
    classList: {
      _s: new Set(),
      add(...c) { c.forEach(x => this._s.add(x)); },
      remove(...c) { c.forEach(x => this._s.delete(x)); },
      toggle(c, f) { const on = f === undefined ? !this._s.has(c) : !!f; on ? this._s.add(c) : this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    appendChild(c) { this.children.push(c); return c; },
    insertAdjacentHTML() {},
    addEventListener() {},
    removeEventListener() {},
    setAttribute() {},
    getAttribute() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {}, click() {}, scrollIntoView() {},
  };
  return el;
}

const els = new Map();
const getEl = id => { if (!els.has(id)) els.set(id, mkEl(id)); return els.get(id); };

// 键监听必须真的收下来,直接调 nextSentence() 会漏掉真正的故障:
// 用户报的是「按 ← → 是上下页」,而那是 keydown 里路由错了,不是
// nextSentence 本身坏了。2026-09-30 就是这么漏过去的。
const keyHandlers = [];
const document = {
  getElementById: getEl,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: tag => mkEl('new-' + tag),
  createDocumentFragment: () => mkEl('frag'),
  body: mkEl('body'),
  addEventListener: (type, fn) => { if (type === 'keydown') keyHandlers.push(fn); },
  documentElement: mkEl('html'),
};
document.documentElement.style.setProperty = () => {};

const sandbox = {
  console,
  document,
  window: null,
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  location: { search: '', href: '' },
  navigator: { mediaDevices: null, clipboard: { writeText: async () => {} } },
  setTimeout: () => 0,
  clearTimeout: () => {},
  setInterval: () => 0,
  clearInterval: () => {},
  fetch: async () => ({ ok: true, json: async () => ({ success: true, book }) }),
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} },
  Blob: class {}, FileReader: class { readAsDataURL() {} },
  Audio: class { play() {} pause() {} addEventListener() {} },
  speechSynthesis: { speak() {}, cancel() {} },
  SpeechSynthesisUtterance: class {},
  alert: () => {}, confirm: () => true, prompt: () => null,
  Math, JSON, Date, Array, Object, String, Number, Boolean, Error, Promise, Set, Map,
  isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent, btoa: () => '', atob: () => '',
  addEventListener: () => {},
  // sync.js 在真页面里由 <script> 单独加载,这里不引入它 —— 上报不是被测对象。
  shadowReport: () => {},
  indexedDB: {
    open: () => ({ onsuccess: null, onupgradeneeded: null, onerror: null,
                   result: { createObjectStore: () => ({ put: () => {}, get: () => ({}) }), objectStoreNames: { contains: () => false } } }),
  },
  crypto: { getRandomValues: (a) => a },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;

const code = fs.readFileSync(path.join(ROOT, 'web/js/index.js'), 'utf8');
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: 'index.js' });

// 顶层 `let`/`const` 属于脚本词法环境,不会挂到 sandbox 上,
// 所以补一个闭包探针把它们读出来(函数声明是能直接拿到的)。
vm.runInContext(
  'globalThis.__probe = () => ({ sentences, chapterStarts, ' +
  'currentSentenceIndex, currentChapterIndex, bookData, sentencesPerPage, readingMode });',
  sandbox);
const P = () => sandbox.__probe();

let fails = 0;
const check = (name, cond, extra) => {
  console.log(`${cond ? '  ✓' : '  ✗'} ${name}${extra ? '  ' + extra : ''}`);
  if (!cond) fails++;
};

(async () => {
  const nCh = book.chapters.length;

  // 密度由 applyReadingDensity 按档案算,测试要逐档跑,就在它算完之后改写状态。
  await sandbox.loadBook('fixture');

  // 每屏句数是动态的(3/4/5/7/10),每一档都得能一路翻到底。
  // 只测一档的话,换档之后跨章逻辑坏掉根本不会有人发现。
  for (const per of [3, 4, 5, 7, 10]) {
    vm.runInContext(`sentencesPerPage = ${per};`, sandbox);

    const total = P().sentences.length;
    if (total !== TOTAL) throw new Error('fixture 句数对不上');
    if (per === 3) {
      console.log(`全书 ${nCh} 章 / ${total} 句 / 每屏 ${per} 句 = ` +
                  `${Math.ceil(total / per)} 屏`);
    }

    // 一路翻到底:「下一页」不能在章末早停。
    // 顺手把每一屏实际显示的句子区间收集起来 —— 真正要保证的不变量是
    // 「全书每一句都恰好出现在一屏上」,一次不多一次不少。
    // 只看「经过了第几章」是不够的:章比一屏还短时(末章 3 句 vs 每屏 10 句),
    // 它永远不会成为某一屏的首句,却实打实印在那一屏上。
    let guard = 0;
    const covered = new Set();
    const expectedPages = Math.ceil(total / per);
    sandbox.selectChapter(0);
    while (guard < 5000) {
      const start = sandbox.pageStartIndex(P().currentSentenceIndex);
      for (let i = start; i < Math.min(start + per, total); i++) covered.add(i);
      const lastPage = expectedPages - 1;
      const page = Math.floor(P().currentSentenceIndex / per);
      if (page >= lastPage) break;
      sandbox.nextPage();
      guard++;
    }
    check(`每屏 ${per} 句:屏数正确`, guard === expectedPages - 1,
          `翻了 ${guard + 1} 屏, 期望 ${expectedPages} 屏`);
    let gaps = 0, dups = 0;
    const seen = new Set();
    for (let i = 0; i < total; i++) {
      if (!covered.has(i)) gaps++;
    }
    // 重复:同一句落在两屏上
    const ranges = [];
    sandbox.selectChapter(0);
    for (let p = 0; p < expectedPages; p++) {
      const start = sandbox.pageStartIndex(P().currentSentenceIndex);
      ranges.push([start, Math.min(start + per, total)]);
      if (p < expectedPages - 1) sandbox.nextPage();
    }
    for (const [a, b] of ranges) {
      for (let i = a; i < b; i++) { if (seen.has(i)) dups++; seen.add(i); }
    }
    check(`每屏 ${per} 句:全书每一句都显示到`, gaps === 0, `漏了 ${gaps} 句`);
    check(`每屏 ${per} 句:没有句子重复显示`, dups === 0, `重复 ${dups} 句`);
    check(`每屏 ${per} 句:末屏包含全书最后一句`,
          ranges[ranges.length - 1][1] === total,
          `末屏 ${ranges[ranges.length - 1][0]}~${ranges[ranges.length - 1][1] - 1}`);

    // 每章下标都能正确定位
    let reachable = 0;
    const starts = P().chapterStarts;
    for (let ci = 0; ci < nCh; ci++) {
      sandbox.jumpTo(starts[ci]);
      if (sandbox.chapterIndexOf(P().currentSentenceIndex) === ci) reachable++;
    }
    check(`每屏 ${per} 句:每章下标都能定位`, reachable === nCh, `${reachable}/${nCh}`);

    // 跨章:本章末句翻一下就进下一章
    sandbox.jumpTo(starts[1] - 1);
    const before = sandbox.chapterIndexOf(P().currentSentenceIndex);
    sandbox.nextPage();
    const after = sandbox.chapterIndexOf(P().currentSentenceIndex);
    check(`每屏 ${per} 句:从本章末句翻页进下一章`, after > before, `章 ${before} -> ${after}`);

    // 进度仍存章内下标(API 契约不变)
    sandbox.jumpTo(starts[2] + 5);
    const ci = sandbox.chapterIndexOf(P().currentSentenceIndex);
    const rel = P().currentSentenceIndex - starts[ci];
    check(`每屏 ${per} 句:进度存章内下标`, ci === 2 && rel === 5,
          `chapter=${ci} sentence=${rel}`);

    // 方向键走句子,不是走整页(用户 2026-09-30 明确要求)。
    // 关键性质:一次只 +1,且页面只在越过本页末句时才翻 ——
    // 页内挪动时正文纹丝不动是故意的,靠「当前句」高亮给出反馈。
    sandbox.jumpTo(0);
    let steps = 1, badStep = null, badTurn = null;
    for (let k = 0; k < 40; k++) {
      const before = P().currentSentenceIndex;
      const beforePage = sandbox.pageStartIndex(before);
      sandbox.nextSentence();
      const after = P().currentSentenceIndex;
      if (after - before !== 1) { badStep = `idx ${before}->${after}`; break; }
      const afterPage = sandbox.pageStartIndex(after);
      const turned = afterPage !== beforePage;
      // 越界当且仅当 after 是新一页的第一句
      const shouldTurn = after % per === 0;
      if (turned !== shouldTurn && badTurn === null) {
        badTurn = `idx ${after} 翻页=${turned} 期望=${shouldTurn}`;
      }
      if (after === before + 1) steps++;
    }
    check(`每屏 ${per} 句:方向键一次只走一句`, badStep === null, badStep || `${steps} 步都 +1`);
    check(`每屏 ${per} 句:只在越过本页末句时才翻页`, badTurn === null, badTurn || '翻页时机正确');

    // 反向同理,且在全书第一句处停住
    sandbox.jumpTo(0);
    sandbox.prevSentence();
    check(`每屏 ${per} 句:在第一句处往回不动`, P().currentSentenceIndex === 0,
          `idx=${P().currentSentenceIndex}`);
    sandbox.jumpTo(total - 1);
    sandbox.nextSentence();
    check(`每屏 ${per} 句:在最后一句处往前不动`, P().currentSentenceIndex === total - 1,
          `idx=${P().currentSentenceIndex} / ${total - 1}`);

    // 方向键要能从末句一路走到全书每一句(不会被某处卡住)
    sandbox.jumpTo(0);
    let reached = new Set([0]);
    while (P().currentSentenceIndex < total - 1 && reached.size < total + 5) {
      sandbox.nextSentence();
      reached.add(P().currentSentenceIndex);
    }
    check(`每屏 ${per} 句:方向键能读到全书每一句`, reached.size === total,
          `走到 ${reached.size}/${total} 句`);

    // 真正按一次方向键,而不是调函数:keydown 里若还路由到 prevPage/nextPage,
    // 上面那些 nextSentence 直调全都会绿。2026-09-30 的故障正是在这里。
    getEl('reader-page').classList.add('active');
    const press = key => {
      const ev = { key, preventDefault() {}, stopPropagation() {} };
      keyHandlers.forEach(fn => fn(ev));
    };
    sandbox.jumpTo(0);
    press('ArrowRight');
    check(`每屏 ${per} 句:按 → 只前进一句`, P().currentSentenceIndex === 1,
          `idx=${P().currentSentenceIndex}`);
    press('ArrowLeft');
    press('ArrowLeft');
    check(`每屏 ${per} 句:在首句按 ← 不动`, P().currentSentenceIndex === 0,
          `idx=${P().currentSentenceIndex}`);
    // 从页中往回:整屏回退会一下退到本页第一句,句级回退只退一句
    sandbox.jumpTo(per + 1);
    press('ArrowLeft');
    check(`每屏 ${per} 句:按 ← 只后退一句`, P().currentSentenceIndex === per,
          `idx=${P().currentSentenceIndex}`);
    // 连按到本页末句之外,页面要跟着翻
    sandbox.jumpTo(per - 1);
    press('ArrowRight');
    check(`每屏 ${per} 句:按 → 越过本页末句才翻页`,
          P().currentSentenceIndex === per,
          `idx=${P().currentSentenceIndex}`);
  }

  // === 查词弹窗的渲染(用户 2026-09-30 报「查询总是失败」)===
  // 真跑 lookupWord + 真 fetch stub,验的是最终写进 DOM 的那段 HTML。
  // 查词曾经 100% 失败,根因是前端直连一个连不上的域名;这里要钉住
  // 「成功时给中文释义」「上游挂了要说网络问题而不是『没查到』」。
  const realFetch = sandbox.fetch;
  const dictResp = payload => async () => ({
    ok: true, status: 200, json: async () => payload,
  });
  const fakeWordEl = mkEl('w');
  const fakeEvent = { stopPropagation() {}, preventDefault() {} };

  sandbox.fetch = dictResp({ success: true, word: 'enchanted',
    phonetic: 'ɪnˈtʃɑːntɪd',
    meanings: [{ part: 'adj.', cn: '迷人的；有魔力的' }] });
  await sandbox.lookupWord('enchanted', fakeWordEl, fakeEvent);
  let modalHtml = getEl('modal-meanings').innerHTML;
  check('查词:成功时弹出中文释义', modalHtml.includes('迷人的；有魔力的'));
  check('查词:音标显示为 /.../ 形式',
        getEl('modal-phonetic').textContent === '/ɪnˈtʃɑːntɪd/',
        getEl('modal-phonetic').textContent);

  // 释义来自上游,直接拼进 innerHTML 就是 XSS 口子。真的塞一个标签进去验。
  sandbox.fetch = dictResp({ success: true, word: 'x', phonetic: 'x',
    meanings: [{ part: 'n.', cn: '<img src=x onerror=alert(1)>' }] });
  await sandbox.lookupWord('xss', fakeWordEl, fakeEvent);
  modalHtml = getEl('modal-meanings').innerHTML;
  check('查词:上游文本已转义(没拼出真标签)',
        !modalHtml.includes('<img') && modalHtml.includes('&lt;img'),
        modalHtml.slice(0, 100).replace(/\n\s*/g, ' '));

  sandbox.fetch = dictResp({ success: false, retryable: true, error: '词典连不上' });
  await sandbox.lookupWord('castle', fakeWordEl, fakeEvent);
  modalHtml = getEl('modal-meanings').innerHTML;
  check('查词:上游挂掉时提示网络而不是「没查到」',
        modalHtml.includes('网络') && !modalHtml.includes('没查到这个词'), modalHtml.slice(0, 90));

  sandbox.fetch = dictResp({ success: true, word: 'zzz', phonetic: '', meanings: [] });
  await sandbox.lookupWord('zzzq', fakeWordEl, fakeEvent);
  modalHtml = getEl('modal-meanings').innerHTML;
  check('查词:查无此词才说「没查到这个词」',
        modalHtml.includes('没查到这个词'), modalHtml.slice(0, 90));

  sandbox.fetch = async () => { throw new Error('network down'); };
  await sandbox.lookupWord('wizard', fakeWordEl, fakeEvent);
  modalHtml = getEl('modal-meanings').innerHTML;
  check('查词:自己家的接口也挂掉时提示检查网络',
        modalHtml.includes('网络'), modalHtml.slice(0, 90));
  sandbox.fetch = realFetch;

  console.log(fails === 0 ? '\n全部通过' : `\n${fails} 项失败`);
  process.exit(fails === 0 ? 0 : 1);
})();
