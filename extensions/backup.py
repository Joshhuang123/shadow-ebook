"""
Owns: 备份的**实现**与 HTTP 接口(/api/backup)—— 创建 / 列表 / 下载 / 删除。
Does NOT own: 定时调度(不做自动备份,备份由家长在页面上手动触发)。

为什么先拍快照再打包(2026-09-30):
    app 用 SQLite WAL 模式(db.py: PRAGMA journal_mode=WAL),已提交的写入
    先落在 shadow.db-wal,等 checkpoint 才并进 shadow.db。所以「只打包
    shadow.db、把 -wal 排除掉」丢的正是最新的数据 —— 排除 WAL 不是避免
    不一致,是制造静默丢失。实测恢复这样打出来的备份,恢复出来的库一张
    表都没有。

    这里用 Python 的 sqlite3 备份 API(src.backup(dst)),它是在线快照:
    app 照常运行、照常写入也能拿到一致的单文件副本。

为什么留 KEEP_COUNT 而不是按天:
    备份是手动触发的,频率取决于家长,「保留 N 天」在这种情况下没有意义
    —— 一周备十次,14 天后可能一份都不剩。按份数留更符合直觉。
"""
import logging
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

from flask import jsonify, request, send_file

from extensions.auth import require_parent_auth, _api_rate_limit_ok

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / 'data'
BACKUP_DIR = ROOT_DIR / 'backups'
DB_FILENAME = 'shadow.db'

# 保留份数(含新生成的那份)
KEEP_COUNT = 5
# 打包时跳过的运行时产物
_EXCLUDE = {'.secret', 'shadow.log', DB_FILENAME,
            f'{DB_FILENAME}-wal', f'{DB_FILENAME}-shm'}
_EXCLUDE_PREFIX = '.secret'

# 只认自己生成的文件名。下载/删除都拿用户给的字符串拼路径,不校验就成了
# 任意文件读取(../../etc/passwd 之类),所以这里卡死格式。
_NAME_RE = re.compile(r'^shadow-data-\d{8}-\d{6}\.tar\.gz$')


def _data_dir() -> Path:
    return DATA_DIR


def _backup_dir() -> Path:
    return BACKUP_DIR


def _snapshot_db(db_path: Path, dest: Path) -> bool:
    """把 WAL 模式的库拍成一致的单文件副本。返回是否成功。"""
    if not db_path.exists():
        return False
    try:
        src = sqlite3.connect(str(db_path))
    except sqlite3.Error as e:
        logger.warning('备份:打不开数据库 %s: %s', db_path, e)
        return False
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.Error as e:
        logger.warning('备份:数据库快照失败 %s: %s', db_path, e)
        # sqlite3.connect 会先把目标文件建出来(哪怕是 0 字节),快照失败后
        # 那个空壳还留在暂存目录里,于是包里会出现一个「看着在、其实空的」
        # shadow.db。必须删掉,不然恢复的人以为数据库备份好了。
        dest.unlink(missing_ok=True)
        return False
    finally:
        src.close()
    return True


def _prune(backup_dir: Path, keep: int = KEEP_COUNT) -> list:
    """只留最新的 keep 份,其余删掉。返回被删掉的文件名。"""
    archives = sorted(backup_dir.glob('shadow-data-*.tar.gz'),
                      key=lambda p: p.name, reverse=True)
    removed = []
    for old in archives[keep:]:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError as e:
            logger.warning('备份:删不掉旧备份 %s: %s', old.name, e)
    return removed


def create_backup(data_dir: Path = None, backup_dir: Path = None,
                  keep: int = KEEP_COUNT):
    """打一个备份。返回 (归档路径, 被删掉的旧备份名列表)。

    失败抛异常,由调用方决定怎么告诉用户 —— 备份失败必须是显式的,
    悄悄返回一个坏文件比报错更糟。
    """
    data_dir = Path(data_dir) if data_dir else _data_dir()
    backup_dir = Path(backup_dir) if backup_dir else _backup_dir()

    if not data_dir.is_dir():
        raise FileNotFoundError(f'data/ 不存在({data_dir})')

    backup_dir.mkdir(parents=True, exist_ok=True)
    name = f'shadow-data-{time.strftime("%Y%m%d-%H%M%S")}.tar.gz'
    out = backup_dir / name

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        (stage / 'data').mkdir()

        _snapshot_db(data_dir / DB_FILENAME, stage / 'data' / DB_FILENAME)

        for item in sorted(data_dir.iterdir()):
            if item.name in _EXCLUDE or item.name.startswith(_EXCLUDE_PREFIX):
                continue
            if item.is_dir():
                shutil.copytree(item, stage / 'data' / item.name)
            else:
                shutil.copy2(item, stage / 'data' / item.name)

        # arcname 固定成 'data',这样解到哪儿都是 data/,不会带上本机路径
        with tarfile.open(out, 'w:gz') as tf:
            tf.add(stage / 'data', arcname='data')

    removed = _prune(backup_dir, keep)
    logger.info('备份完成: %s (%d bytes), 清掉 %d 份旧备份',
                name, out.stat().st_size, len(removed))
    return out, removed


def list_backups(backup_dir: Path = None) -> list:
    """按时间倒序列出备份。最新在前。"""
    backup_dir = Path(backup_dir) if backup_dir else _backup_dir()
    if not backup_dir.is_dir():
        return []
    items = []
    for p in backup_dir.glob('shadow-data-*.tar.gz'):
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({
            'name': p.name,
            'size': st.st_size,
            'mtime': int(st.st_mtime),
        })
    items.sort(key=lambda x: x['name'], reverse=True)
    return items


def resolve(name: str):
    """把用户给的文件名解析成路径;格式不对返回 None。"""
    if not name or not _NAME_RE.match(name):
        return None
    path = _backup_dir() / name
    # 即便格式过了也再确认一次没跑出 backups/ —— 纵深防御
    try:
        if path.resolve().parent != _backup_dir().resolve():
            return None
    except OSError:
        return None
    return path if path.is_file() else None


def register_routes(app):
    # 备份里含家长 PIN 哈希、全部书目、孩子的阅读进度,四个接口一律要 PIN。
    # 注意:GET /api/backup 也要鉴权 —— 「有哪些备份、什么时候备的」本身就是
    # 隐私信息,孩子端不该看见。

    @app.route('/api/backup', methods=['GET'])
    @require_parent_auth
    def backup_list():
        return jsonify({'success': True, 'backups': list_backups(),
                        'keep': KEEP_COUNT})

    @app.route('/api/backup', methods=['POST'])
    @require_parent_auth
    def backup_create():
        ok, retry = _api_rate_limit_ok(request.remote_addr or 'unknown', 'backup')
        if not ok:
            return jsonify({'success': False,
                            'error': f'刚备过,等 {retry} 秒再试',
                            'retryable': True, 'retry_after': retry}), 429
        try:
            out, removed = create_backup()
        except Exception as e:
            logger.exception('备份失败')
            return jsonify({'success': False,
                            'error': f'备份失败:{e}'}), 500
        return jsonify({
            'success': True,
            'name': out.name,
            'size': out.stat().st_size,
            'removed': removed,
            'backups': list_backups(),
        })

    @app.route('/api/backup/<name>', methods=['GET'])
    @require_parent_auth
    def backup_download(name):
        path = resolve(name)
        if not path:
            return jsonify({'success': False, 'error': '备份不存在'}), 404
        return send_file(str(path), as_attachment=True, download_name=name)

    @app.route('/api/backup/<name>', methods=['DELETE'])
    @require_parent_auth
    def backup_delete(name):
        path = resolve(name)
        if not path:
            return jsonify({'success': False, 'error': '备份不存在'}), 404
        try:
            path.unlink()
        except OSError as e:
            return jsonify({'success': False, 'error': f'删不掉:{e}'}), 500
        return jsonify({'success': True, 'backups': list_backups()})
