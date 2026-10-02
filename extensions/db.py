"""
Owns: SQLite connection + schema + init + first-startup migration + raw query helpers.
Does NOT own: domain logic (books.py owns books CRUD, parent_data.py owns parent data).

Phase 3b 完成: books / parent_data / parent_pin 全部走 SQLite。
R22 拆表: parent 学习数据行级化 (parent_section / vocab_reviews /
book_progress / sentence_mastery), 旧单行 blob 首启自动迁入并保留作快照。
首启自动把 data/books/*.json + data/parent/{data.json,pin.hash} 迁进 DB,
原文件备份到 data/{books,parent}.migrated-<ts>/ 留 30 天。
"""
import json
import logging
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


logger = logging.getLogger(__name__)


DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
DB_PATH = DATA_DIR / 'shadow.db'
BOOKS_JSON_DIR = DATA_DIR / 'books'


# === SQLite schema ===
# books (Phase 3a): 单内容列 data_json 保留 book/author/description/chapters/cover 全部字段
# parent_data / parent_pin (Phase 3b): 单行表 (id=1);R22 拆表后 parent_data 行
#   只是拆表前快照 (不再读写),学习数据在下面的 parent_section / vocab_reviews /
#   book_progress / sentence_mastery 四张表
# generated_questions (R21): LLM 出题的缓存,防重复 + 自动毕业已掌握题
SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id TEXT PRIMARY KEY,
  data_json TEXT NOT NULL,
  imported_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_books_updated ON books(updated_at DESC);

CREATE TABLE IF NOT EXISTS parent_data (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  data_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS parent_pin (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  pin_hash TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  grammar_key TEXT NOT NULL,
  question_json TEXT NOT NULL,
  question_text TEXT NOT NULL,
  used_count INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  UNIQUE(user_id, grammar_key, question_text)
);
CREATE INDEX IF NOT EXISTS idx_gen_q_lookup
  ON generated_questions(user_id, grammar_key, used_count, created_at DESC);

-- dict_cache: 查词结果缓存。查词是「同一个词被点很多次」的场景
-- (点一次查一次,生词本里再复习又点一次),每次都打第三方既慢又白给配额。
-- 存 payload 原样,所以换解析逻辑时可以按需 bump found_at 强制重取。
CREATE TABLE IF NOT EXISTS dict_cache (
  word TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  found INTEGER NOT NULL,        -- 0 = 上游确实没有这个词(负缓存)
  fetched_at INTEGER NOT NULL
);

-- === R22 拆表: parent_data 单行 blob 的行级化 ===
-- 之前全部学习数据塞在 parent_data 单行 JSON 里,阅读器每读一句、每次查词
-- 都是 read-modify-write 整个 blob: O(全量) 且并发下 last-write-wins 互相覆盖。
-- 热数据(每句/每词的写)拆成行级表,小配置(stats/settings/vocabulary)保留
-- 整段 JSON —— 它们本来就是「深度合并」语义,段内数据量小,不值得行化。
CREATE TABLE IF NOT EXISTS parent_section (
  name TEXT PRIMARY KEY,         -- stats / settings / vocabulary
  data_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

-- SRS 复习状态: 一词一行。到期队列/四桶统计/薄弱词全部走索引,不再全表扫 dict。
CREATE TABLE IF NOT EXISTS vocab_reviews (
  word TEXT PRIMARY KEY,
  state TEXT NOT NULL DEFAULT 'learning',
  added_ts INTEGER NOT NULL,
  next_review_ts INTEGER NOT NULL,
  last_review_ts INTEGER,
  review_count INTEGER NOT NULL DEFAULT 0,
  correct_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_vocab_reviews_due ON vocab_reviews(next_review_ts);

-- 阅读进度: 一书一行。
CREATE TABLE IF NOT EXISTS book_progress (
  book_id TEXT PRIMARY KEY,
  chapter_idx INTEGER NOT NULL,
  sentence_idx INTEGER NOT NULL,
  last_open_ts INTEGER NOT NULL
);

-- 句子熟练度: 一句一行 —— 原整表重写的大头(每本书每句一条,阅读器每读一句写一次)。
CREATE TABLE IF NOT EXISTS sentence_mastery (
  book_id TEXT NOT NULL,
  chapter_idx INTEGER NOT NULL,
  sentence_idx INTEGER NOT NULL,
  mastery TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_attempt_ts INTEGER NOT NULL,
  PRIMARY KEY (book_id, chapter_idx, sentence_idx)
);
"""


# === thread-local connection ===
_local = threading.local()


def get_db():
    """返回 thread-local SQLite 连接 (WAL 模式,支持并发读)。"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), isolation_level=None)  # autocommit
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute('PRAGMA journal_mode=WAL')
        _local.conn.execute('PRAGMA foreign_keys=ON')
    return _local.conn


@contextmanager
def write_txn():
    """显式写事务 (BEGIN IMMEDIATE),包住「读 → 改 → 写」序列。

    为什么需要:autocommit 下单条语句原子,但两条语句之间的读会被别的
    进程插进来 —— gunicorn -w 2 时两个 worker 同时 deep-merge /api/parent/data,
    后提交的会把先提交的写丢掉 (last-write-wins)。BEGIN IMMEDIATE 一开始
    就拿写锁,序列化整个读改写,跨进程也成立。

    用法:
        with write_txn() as conn:
            ...SELECT / INSERT / UPDATE...
    异常自动 ROLLBACK,正常退出 COMMIT。不要嵌套使用。
    """
    conn = get_db()
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        try:
            conn.execute('ROLLBACK')
        except sqlite3.Error:
            pass
        raise
    conn.execute('COMMIT')


# === 首次启动:建表 + 一次性 JSON→SQLite 迁移 (per-domain marker) ===
def init_db():
    """幂等。每个域独立检查自己的 migration marker,任何域没迁就迁,跑过就跳过。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()

    # Books migration (Phase 3a)
    if not (DATA_DIR / '.migration_marker').exists():
        _migrate_books_from_json()
        (DATA_DIR / '.migration_marker').write_text(
            f'books migrated at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
            f'原 JSON 备份在 data/books.migrated-<ts>/ (留 30 天,后手动 rm)\n'
        )

    # Parent migration (Phase 3b)
    if not (DATA_DIR / '.parent_migrated').exists():
        _migrate_parent_from_json()
        (DATA_DIR / '.parent_migrated').write_text(
            f'parent data/pin migrated at {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
            f'原文件备份在 data/parent.migrated-<ts>/ (留 30 天,后手动 rm)\n'
        )

    # R22: parent_data 单行 blob → 拆表 (必须在 parent JSON 迁移之后 ——
    # 古老部署会先把 parent/*.json 灌进 parent_data 行,这里再拆进新表)
    if not (DATA_DIR / '.parent_split_migrated').exists():
        _migrate_parent_split()
        (DATA_DIR / '.parent_split_migrated').write_text(
            f'parent_data 单行 blob 拆表迁移于 {time.strftime("%Y-%m-%dT%H:%M:%S")}\n'
            f'旧 blob 行保留在 parent_data 表作拆表前快照, 不再读写\n'
        )

    # R11: 清理过期备份目录 (>30 天的 books.migrated-* / parent.migrated-*)
    _cleanup_old_migrations(days=30)


def _cleanup_old_migrations(days: int = 30):
    """删 N 天前的 .migrated-* 备份目录。Init 末尾跑,不阻塞首启。"""
    cutoff = time.time() - days * 86400
    removed = 0
    for pattern in ('books.migrated-*', 'parent.migrated-*'):
        for d in DATA_DIR.glob(pattern):
            if not d.is_dir():
                continue
            try:
                # 目录名带 int(time.time()), 直接 parse
                ts_str = d.name.split('.migrated-', 1)[-1]
                ts = int(ts_str)
                if ts < cutoff:
                    shutil.rmtree(d)
                    removed += 1
            except (ValueError, OSError) as e:
                logger.debug(f'跳过 {d}: {e}')
    if removed:
        logger.info(f'清理 {removed} 个过期迁移备份 (>{days} 天)')


_SPLIT_SECTIONS = ('stats', 'vocabulary', 'settings')


def _migrate_parent_split():
    """一次性: parent_data 旧单行 blob → parent_section / vocab_reviews /
    book_progress / sentence_mastery。

    旧 blob 行迁完保留不删 —— 冻结的拆表前快照,万一新表出问题还能回捞,
    没有任何代码再读它。整个复制过程在单个事务里: 要么全进新表,要么
    什么都不动,不存在「迁了一半」的中间态。
    """
    conn = get_db()
    row = conn.execute('SELECT data_json FROM parent_data WHERE id = 1').fetchone()
    if not row:
        return  # 全新安装,没有旧数据
    try:
        old = json.loads(row['data_json'])
    except Exception as e:
        logger.warning(f'parent_data 旧 blob 解析失败, 跳过拆表迁移: {e}')
        return
    if not isinstance(old, dict):
        logger.warning('parent_data 旧 blob 不是 dict, 跳过拆表迁移')
        return

    now = int(time.time() * 1000)
    with write_txn():
        for name in _SPLIT_SECTIONS:
            val = old.get(name)
            if isinstance(val, dict) and val:
                conn.execute(
                    'INSERT OR IGNORE INTO parent_section (name, data_json, updated_at) '
                    'VALUES (?, ?, ?)',
                    (name, json.dumps(val, ensure_ascii=False), now),
                )

        for word, r in (old.get('vocabReviews') or {}).items():
            if not isinstance(r, dict):
                continue
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO vocab_reviews '
                    '(word, state, added_ts, next_review_ts, last_review_ts, review_count, correct_count) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (str(word), str(r.get('state') or 'learning'),
                     int(r.get('added_ts') or now), int(r.get('next_review_ts') or 0),
                     int(r['last_review_ts']) if r.get('last_review_ts') is not None else None,
                     int(r.get('review_count') or 0), int(r.get('correct_count') or 0)),
                )
            except (TypeError, ValueError) as e:
                logger.warning(f'vocabReviews 迁移跳过 {word!r}: {e}')

        for book_id, p in (old.get('bookProgress') or {}).items():
            if not isinstance(p, dict):
                continue
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO book_progress (book_id, chapter_idx, sentence_idx, last_open_ts) '
                    'VALUES (?, ?, ?, ?)',
                    (str(book_id), int(p.get('chapter_idx') or 0),
                     int(p.get('sentence_idx') or 0), int(p.get('last_open_ts') or now)),
                )
            except (TypeError, ValueError) as e:
                logger.warning(f'bookProgress 迁移跳过 {book_id!r}: {e}')

        for book_id, chapters in (old.get('sentenceMastery') or {}).items():
            if not isinstance(chapters, dict):
                continue
            for ch, sents in chapters.items():
                if not isinstance(sents, dict):
                    continue
                for idx, m in sents.items():
                    if not isinstance(m, dict):
                        continue
                    try:
                        conn.execute(
                            'INSERT OR IGNORE INTO sentence_mastery '
                            '(book_id, chapter_idx, sentence_idx, mastery, attempts, last_attempt_ts) '
                            'VALUES (?, ?, ?, ?, ?, ?)',
                            (str(book_id), int(ch), int(idx),
                             str(m.get('mastery') or 'attempted'),
                             int(m.get('attempts') or 0), int(m.get('last_attempt_ts') or now)),
                        )
                    except (TypeError, ValueError) as e:
                        logger.warning(f'sentenceMastery 迁移跳过 {book_id}/{ch}/{idx}: {e}')

    logger.info('parent_data 单行 blob 已拆表迁入 parent_section / vocab_reviews / '
                'book_progress / sentence_mastery (旧行保留作快照)')


def _migrate_books_from_json():
    """首次启动:把 data/books/*.json 灌进 SQLite,原文件移到 .migrated-<ts>/ 留底。"""
    if not BOOKS_JSON_DIR.exists():
        return

    json_files = list(BOOKS_JSON_DIR.glob('*.json'))
    if not json_files:
        return

    backup_dir = DATA_DIR / f'books.migrated-{int(time.time())}'
    backup_dir.mkdir(exist_ok=True)

    conn = get_db()
    now = int(time.time() * 1000)
    migrated = 0
    failed = 0
    for f in json_files:
        try:
            data = json.loads(f.read_text())
            book_id = f.stem
            data_json = json.dumps(data, ensure_ascii=False)
            conn.execute(
                'INSERT OR REPLACE INTO books (id, data_json, imported_at, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (book_id, data_json, now, now)
            )
            shutil.move(str(f), str(backup_dir / f.name))
            migrated += 1
        except Exception as e:
            logger.warning(f'迁移 {f.name} 失败: {e}')
            failed += 1

    logger.info(f'books 迁移完成: {migrated} 成功, {failed} 失败, 备份在 {backup_dir.name}/')


def _migrate_parent_from_json():
    """首次启动:把 data/parent/data.json + pin.hash 灌进 SQLite,原文件备份到 .migrated-<ts>/。"""
    parent_dir = DATA_DIR / 'parent'
    if not parent_dir.exists():
        return

    data_file = parent_dir / 'data.json'
    pin_file = parent_dir / 'pin.hash'
    if not data_file.exists() and not pin_file.exists():
        return

    backup_dir = DATA_DIR / f'parent.migrated-{int(time.time())}'
    backup_dir.mkdir(exist_ok=True)

    conn = get_db()
    now = int(time.time() * 1000)

    if data_file.exists():
        try:
            data = json.loads(data_file.read_text())
            conn.execute(
                'INSERT OR REPLACE INTO parent_data (id, data_json, updated_at) VALUES (1, ?, ?)',
                (json.dumps(data, ensure_ascii=False), now)
            )
            shutil.move(str(data_file), str(backup_dir / 'data.json'))
            logger.info(f'parent_data 迁移完成, 备份在 {backup_dir.name}/')
        except Exception as e:
            logger.warning(f'parent_data 迁移失败: {e}')

    if pin_file.exists():
        try:
            pin_hash = pin_file.read_text().strip()
            conn.execute(
                'INSERT OR REPLACE INTO parent_pin (id, pin_hash, updated_at) VALUES (1, ?, ?)',
                (pin_hash, now)
            )
            shutil.move(str(pin_file), str(backup_dir / 'pin.hash'))
            logger.info(f'parent_pin 迁移完成, 备份在 {backup_dir.name}/')
        except Exception as e:
            logger.warning(f'parent_pin 迁移失败: {e}')