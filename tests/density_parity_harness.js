// 真跑 web/js/index.js 里的 computeDensity,和 Python 逐档对账。
// 密度公式在前后端各有一份(sed 复制的东西迟早会漂),这个 harness 就是防漂的。
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const { execFileSync } = require('child_process');

const REPO = '/Users/huangjunhai/shadow-learning';

function mkEl(id) {
  return {
    id, textContent: '', innerHTML: '', value: '', hidden: false, disabled: false,
    style: { setProperty() {} }, dataset: {}, children: [], files: [], className: '',
    classList: {
      _s: new Set(),
      add(...c) { c.forEach(x => this._s.add(x)); },
      remove(...c) { c.forEach(x => this._s.delete(x)); },
      toggle() {}, contains(c) { return this._s.has(c); },
    },
    appendChild(c) { return c; }, insertAdjacentHTML() {},
    addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    focus() {}, click() {}, scrollIntoView() {},
  };
}
const els = new Map();
const getEl = id => { if (!els.has(id)) els.set(id, mkEl(id)); return els.get(id); };
const document = {
  getElementById: getEl, querySelector: () => null, querySelectorAll: () => [],
  createElement: t => mkEl('new-' + t), createDocumentFragment: () => mkEl('frag'),
  body: mkEl('body'), addEventListener() {},
  documentElement: Object.assign(mkEl('html'), { style: { setProperty() {} } }),
};

const sandbox = {
  console, document, window: null, location: { search: '', href: '' },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  navigator: { mediaDevices: null, clipboard: { writeText: async () => {} } },
  setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
  fetch: async () => ({ ok: true, json: async () => ({ success: true, child: {} }) }),
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  Blob: class {}, FileReader: class { readAsDataURL() {} },
  Audio: class { play() {} pause() {} addEventListener() {} },
  speechSynthesis: { speak() {}, cancel() {} }, SpeechSynthesisUtterance: class {},
  alert() {}, confirm: () => true, prompt: () => null, addEventListener() {},
  indexedDB: { open: () => ({ result: { createObjectStore: () => ({ put() {}, get: () => ({}) }), objectStoreNames: { contains: () => false } } }) },
  crypto: { getRandomValues: a => a },
  Math, JSON, Date, Array, Object, String, Number, Boolean, Error, Promise, Set, Map,
  isNaN, parseInt, parseFloat, encodeURIComponent, decodeURIComponent, btoa: () => '', atob: () => '',
};
sandbox.window = sandbox; sandbox.globalThis = sandbox; sandbox.self = sandbox;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(REPO, 'web/js/index.js'), 'utf8'),
                sandbox, { filename: 'index.js' });
vm.runInContext('globalThis.__computeDensity = computeDensity;', sandbox);

// 覆盖面要盖住每一档的边界,不然 parity 测试等于没测
const CASES = [];
for (const book of [300, 500, 600, 750, 880, 1100]) {
  for (const child of [null, 0, 200, 350, 400, 500, 550, 600, 700, 750, 800, 900, 1200, 2000, 9999, 'abc']) {
    CASES.push([book, child]);
  }
}

const jsOut = CASES.map(([b, c]) => {
  const r = sandbox.__computeDensity(b, c);
  return [b === null ? '' : b, c === null ? '' : c, r.sentencesPerPage, r.mode].join('\t');
}).join('\n');

const pyOut = execFileSync('/Users/huangjunhai/shadow-learning/venv/bin/python', ['-c', `
import sys, json
sys.path.insert(0, ${JSON.stringify(REPO)})
from extensions.books import calc_reading_density
# 走 json.loads 而不是把数组直接插进源码:JS 的 null/字符串在 Python 源码里
# 不是合法字面量,插进去会变成 NameError。
cases = json.loads(sys.argv[1])
for book, child in cases:
    r = calc_reading_density(book, child)
    print(f"{book if book is not None else ''}\t{child if child is not None else ''}\t{r['sentencesPerPage']}\t{r['mode']}")
`, JSON.stringify(CASES)], { encoding: 'utf8', cwd: REPO });

if (jsOut.trim() !== pyOut.trim()) {
  const j = jsOut.trim().split('\n');
  const p = pyOut.trim().split('\n');
  console.error('JS 和 Python 的密度结果不一致:');
  for (let i = 0; i < Math.max(j.length, p.length); i++) {
    if (j[i] !== p[i]) console.error(`  book/child  ${p[i]}\n    JS → ${j[i]}\n    PY → ${p[i]}`);
  }
  process.exit(1);
}
console.log(`JS/Python 密度一致性通过 (${CASES.length} 组)`);
