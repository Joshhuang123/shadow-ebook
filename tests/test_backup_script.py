"""tests/test_backup_script.py — 备份必须真的能恢复。

背景(2026-09-30):
    app 用 SQLite WAL 模式(db.py: PRAGMA journal_mode=WAL),已提交的写入
    先落在 shadow.db-wal,等 checkpoint 才并进 shadow.db。

    原来的 scripts/backup.sh 排除掉 -wal 再打包 shadow.db,注释写着
    「排除避免不一致」。方向反了:排除 WAL 不是避免不一致,是**制造静默
    丢失** —— 丢的恰好是最近写入的数据,而那正是最该被备份的。

    而且它从没被跑过(backups/ 目录压根不存在),所以这个 bug 一直没暴露。
    备份脚本的价值全在「出事那天能恢复」,没跑过的备份等于没有备份,
    所以这里直接跑一遍并真的恢复,而不是只检查脚本能执行。
"""
import shutil
import sqlite3
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / 'scripts' / 'backup.sh'

pytestmark = pytest.mark.skipif(
    shutil.which('sqlite3') is None or shutil.which('tar') is None,
    reason='需要 sqlite3 和 tar')


def _run_backup(tmp_path):
    out = tmp_path / 'backups'
    proc = subprocess.run(
        ['bash', str(SCRIPT)],
        capture_output=True, text=True, timeout=120,
        env={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin',
             'BACKUP_DIR': str(out), 'DATA_DIR': str(tmp_path / 'data'),
             'HOME': str(tmp_path)},
    )
    assert proc.returncode == 0, f'{proc.stdout}\n{proc.stderr}'
    archives = sorted(out.glob('shadow-data-*.tar.gz'))
    assert len(archives) == 1, f'没生成备份: {proc.stdout}'
    return archives[0]


def test_backup_keeps_data_still_in_the_wal(tmp_path):
    """核心回归:只存在于 -wal 里的写入,备份后必须还在。

    旧脚本这一条会红 —— 它排除 -wal,恢复出来的库里查不到这行。
    """
    db_path = tmp_path / 'data' / 'shadow.db'
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE t (k TEXT PRIMARY KEY)')
    conn.execute("INSERT INTO t VALUES ('written-just-now')")
    conn.commit()
    # 别 checkpoint:让这行就留在 -wal 里,模拟「刚写完就备份」
    assert (tmp_path / 'data' / 'shadow.db-wal').exists(), '测试前提不成立:WAL 文件没生成'

    archive = _run_backup(tmp_path)

    restore = tmp_path / 'restored'
    restore.mkdir()
    with tarfile.open(archive) as tf:
        tf.extractall(restore, filter='data')

    got = sqlite3.connect(str(restore / 'data' / 'shadow.db')).execute(
        "SELECT k FROM t WHERE k='written-just-now'").fetchall()
    assert got == [('written-just-now',)], '备份漏掉了还躺在 WAL 里的数据'


def test_backup_excludes_runtime_junk(tmp_path):
    """运行时产物不该进备份:.secret 是密钥,log 可再生且体积大。"""
    data = tmp_path / 'data'
    data.mkdir(parents=True)
    (data / 'shadow.log').write_text('x' * 100)
    (data / '.secret').write_text('deadbeef')
    (data / 'keepme.txt').write_text('重要的东西')
    sqlite3.connect(str(data / 'shadow.db')).close()

    archive = _run_backup(tmp_path)
    restore = tmp_path / 'restored'
    restore.mkdir()
    with tarfile.open(archive) as tf:
        tf.extractall(restore, filter='data')

    assert (restore / 'data' / 'keepme.txt').exists(), '普通文件没进备份'
    assert not (restore / 'data' / '.secret').exists(), '.secret 不该进备份'
    assert not (restore / 'data' / 'shadow.log').exists(), '日志不该进备份'
    assert not (restore / 'data' / 'shadow.db-wal').exists(), 'WAL 不该以碎片形式进备份'
    assert not (restore / 'data' / 'shadow.db-shm').exists()


def test_backup_works_without_a_database_yet(tmp_path):
    """全新装、还没建库时跑备份不该报错(可能是 cron 每天都在跑)。"""
    (tmp_path / 'data').mkdir(parents=True)
    archive = _run_backup(tmp_path)
    with tarfile.open(archive) as tf:
        assert 'data' in tf.getnames()
