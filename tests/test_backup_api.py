"""tests/test_backup_api.py — 家长页那个「立即备份」背后该守住的性质。

三条底线,按重要性排:

1. **不能丢数据。** app 跑在 SQLite WAL 模式,已提交的写入先落在
   shadow.db-wal。早期 backup.sh 排除掉 -wal 只打包 shadow.db,注释还写着
   「排除避免不一致」—— 方向反了,恢复出来的是一张空库。
2. **不能让别人拿走数据。** 备份里是家长 PIN 哈希、全部书目、孩子的阅读
   进度。所以四个接口一律要 PIN,文件名格式必须卡死(否则
   `/api/backup/..%2F..%2Fetc%2Fpasswd` 就是任意文件读取)。
3. **不能默默失败。** 打包出错要抛出来,不能返回一个坏文件还报成功。
"""
import io
import sqlite3
import tarfile
from pathlib import Path

import pytest

from extensions import backup as bk


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    bdir = tmp_path / 'backups'
    monkeypatch.setattr(bk, 'DATA_DIR', data)
    monkeypatch.setattr(bk, 'BACKUP_DIR', bdir)
    return data, bdir


def _seed_db(data: Path, rows=3):
    conn = sqlite3.connect(str(data / 'shadow.db'))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('CREATE TABLE notes (k TEXT PRIMARY KEY)')
    for i in range(rows):
        conn.execute('INSERT INTO notes VALUES (?)', (f'note-{i}',))
    conn.commit()
    return conn


def _members(archive: Path):
    with tarfile.open(archive) as tf:
        return tf.getnames()


def _read_db(archive: Path, name='data/shadow.db', tmp_path=None) -> sqlite3.Connection:
    """把包里的库解到临时文件再打开 —— sqlite3 不接受 BytesIO。"""
    with tarfile.open(archive) as tf:
        blob = tf.extractfile(name).read()
    dest = Path(tmp_path) / 'extracted.db'
    dest.write_bytes(blob)
    return sqlite3.connect(str(dest))


# === 1. 不丢数据 ===

def test_backup_keeps_data_still_in_the_wal(dirs, tmp_path):
    """核心回归:只存在于 -wal 里的写入,备份后必须还在。

    排除 WAL 的旧写法下,恢复出来的库连表都没有。
    """
    data, bdir = dirs
    conn = _seed_db(data)
    assert (data / 'shadow.db-wal').exists(), '前提不成立:WAL 文件没生成'

    out, _ = bk.create_backup(data, bdir)
    got = _read_db(out, tmp_path=tmp_path).execute(
        'SELECT k FROM notes ORDER BY k').fetchall()
    assert [r[0] for r in got] == ['note-0', 'note-1', 'note-2']
    conn.close()


def test_backup_works_with_no_database_yet(dirs):
    """全新装还没建库时点备份,不该 500。"""
    data, bdir = dirs
    out, _ = bk.create_backup(data, bdir)
    assert out.exists()
    assert 'data' in _members(out)[0]


def test_backup_includes_other_data_files(dirs):
    """书目、封面这些不是 SQLite,也得进包。"""
    data, bdir = dirs
    _seed_db(data).close()
    (data / 'covers').mkdir()
    (data / 'covers' / 'a.jpg').write_bytes(b'\xff\xd8fake')
    (data / 'books').mkdir()
    (data / 'books' / 'b.json').write_text('{}')

    out, _ = bk.create_backup(data, bdir)
    names = _members(out)
    assert 'data/covers/a.jpg' in names
    assert 'data/books/b.json' in names


def test_backup_excludes_runtime_junk(dirs):
    """.secret 是密钥、log 可再生且体积大,都不该进包。"""
    data, bdir = dirs
    _seed_db(data).close()
    (data / '.secret').write_text('deadbeef')
    (data / 'shadow.log').write_text('x' * 100)

    out, _ = bk.create_backup(data, bdir)
    names = _members(out)
    assert 'data/shadow.db' in names, '快照必须在'
    assert 'data/.secret' not in names
    assert 'data/shadow.log' not in names
    assert not any(n.endswith('-wal') or n.endswith('-shm') for n in names), \
        'WAL 碎片不该以文件形式进包(已经在快照里了)'


def test_archive_paths_are_relative_to_data(dirs):
    """解到任何地方都该是 data/,不能带上本机绝对路径。"""
    data, bdir = dirs
    _seed_db(data).close()
    out, _ = bk.create_backup(data, bdir)
    for n in _members(out):
        assert n == 'data' or n.startswith('data/'), f'归档内路径不对: {n}'


# === 保留份数 ===

def _fake_archive(bdir: Path, stamp: str) -> Path:
    """造一个占位备份。文件名是秒级时间戳,靠 sleep 造不出多份,
    所以直接按不同时间戳写文件。"""
    bdir.mkdir(parents=True, exist_ok=True)
    p = bdir / f'shadow-data-{stamp}.tar.gz'
    p.write_bytes(b'fake')
    return p


def test_prunes_to_keep_count(dirs):
    """备份是手动点的,按份数留比按天留更符合直觉。"""
    data, bdir = dirs
    for i in range(1, 9):
        _fake_archive(bdir, f'2026090{i}-000000')
    removed = bk._prune(bdir, keep=3)
    assert len(bk.list_backups(bdir)) == 3
    assert len(removed) == 5


def test_prune_keeps_the_newest(dirs):
    _, bdir = dirs
    for i in range(1, 5):
        _fake_archive(bdir, f'2026090{i}-000000')
    bk._prune(bdir, keep=2)
    names = [b['name'] for b in bk.list_backups(bdir)]
    assert names == ['shadow-data-20260904-000000.tar.gz',
                     'shadow-data-20260903-000000.tar.gz'], '留的应该是最新的两份'


def test_list_is_newest_first(dirs):
    _, bdir = dirs
    for i in (3, 1, 2):
        _fake_archive(bdir, f'2026090{i}-000000')
    names = [b['name'] for b in bk.list_backups(bdir)]
    assert names == sorted(names, reverse=True)


def test_create_reports_what_it_removed(dirs):
    """该告诉调用方清掉了哪份,而不是悄悄删。"""
    data, bdir = dirs
    _seed_db(data).close()
    _fake_archive(bdir, '20200101-000000')      # 一份很旧的
    _, removed = bk.create_backup(data, bdir, keep=1)
    assert removed == ['shadow-data-20200101-000000.tar.gz']


def test_backup_failure_raises(dirs):
    """打包失败必须显式抛出来 —— 悄悄返回坏文件比报错更糟。"""
    data, bdir = dirs
    _seed_db(data).close()
    with pytest.raises(FileNotFoundError):
        bk.create_backup(data / 'nope', bdir)


# === 2. 鉴权与路径安全 ===

@pytest.fixture
def app(tmp_path, monkeypatch, clear_api_rate):
    from flask import Flask
    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(bk, 'DATA_DIR', data)
    monkeypatch.setattr(bk, 'BACKUP_DIR', tmp_path / 'backups')
    a = Flask(__name__)
    a.config['TESTING'] = True
    a.config['SECRET_KEY'] = 'test-secret'
    bk.register_routes(a)
    return a


@pytest.fixture
def client(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s['parent_auth'] = True
    return c


@pytest.fixture
def anon(app):
    return app.test_client()


@pytest.mark.parametrize('method,path', [
    ('get', '/api/backup'),
    ('post', '/api/backup'),
    ('get', '/api/backup/shadow-data-20260930-000000.tar.gz'),
    ('delete', '/api/backup/shadow-data-20260930-000000.tar.gz'),
])
def test_every_endpoint_needs_parent_pin(anon, method, path):
    """备份里是 PIN 哈希 + 全部书目 + 阅读进度,孩子端一个都不许碰。"""
    r = getattr(anon, method)(path)
    assert r.status_code == 401, f'{method.upper()} {path} 没要鉴权'


def test_list_requires_pin_even_though_readonly(anon):
    """「有哪些备份、什么时候备的」本身就是隐私,不是无害的读。"""
    assert anon.get('/api/backup').status_code == 401


def test_create_then_list(client, app):
    _seed_db(bk.DATA_DIR).close()
    r = client.post('/api/backup')
    assert r.status_code == 200
    j = r.get_json()
    assert j['success'] is True
    assert len(j['backups']) == 1
    assert client.get('/api/backup').get_json()['backups'][0]['name'] == j['name']


def test_download_returns_the_archive(client, app):
    _seed_db(bk.DATA_DIR).close()
    name = client.post('/api/backup').get_json()['name']
    r = client.get(f'/api/backup/{name}')
    assert r.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(r.data)) as tf:
        assert 'data/shadow.db' in tf.getnames()


def test_delete_removes_it(client, app):
    _seed_db(bk.DATA_DIR).close()
    name = client.post('/api/backup').get_json()['name']
    assert client.delete(f'/api/backup/{name}').status_code == 200
    assert client.get('/api/backup').get_json()['backups'] == []
    assert client.get(f'/api/backup/{name}').status_code == 404


@pytest.mark.parametrize('evil', [
    '../../../etc/passwd',
    '..%2F..%2Fetc%2Fpasswd',
    '/etc/passwd',
    'shadow.db',                      # 格式不对,即使存在也不给
    'shadow-data-20260930-000000.tar.gz/../../../etc/passwd',
])
def test_path_traversal_is_rejected(evil, client, app, tmp_path):
    """文件名是用户给的,不校验就成了任意文件读取。"""
    (tmp_path / 'backups').mkdir(parents=True, exist_ok=True)
    r = client.get(f'/api/backup/{evil}')
    assert r.status_code in (400, 404), f'{evil} 竟然没被挡住'
    assert r.status_code == 404


def test_traversal_cannot_delete_outside(client, app, tmp_path):
    """删除路径同样要挡住 —— 否则能把服务器上的文件删了。"""
    victim = tmp_path / 'victim.txt'
    victim.write_text('别删我')
    assert client.delete('/api/backup/..%2F..%2Fvictim.txt').status_code == 404
    assert victim.exists()


def test_resolve_only_returns_files_inside_backup_dir(client, app, tmp_path, monkeypatch):
    bdir = tmp_path / 'backups'
    bdir.mkdir()
    real = bdir / 'shadow-data-20260930-000000.tar.gz'
    real.write_bytes(b'x')
    outside = tmp_path / 'shadow-data-20990101-000000.tar.gz'
    outside.write_bytes(b'x')
    monkeypatch.setattr(bk, 'BACKUP_DIR', bdir)
    assert bk.resolve(real.name) == real
    assert bk.resolve(outside.name) is None, '同名文件但在 backups/ 之外,不该给'


# === 3. 静默失败 ===

def test_corrupt_database_still_produces_a_backup(client, app):
    """库坏了也要给个包(里面是其余文件),并在日志里留痕 ——
    但绝不能因为库坏就把整个备份搞失败。"""
    (bk.DATA_DIR / 'shadow.db').write_bytes(b'not a database at all')
    (bk.DATA_DIR / 'keep.txt').write_text('别的数据还在')
    r = client.post('/api/backup')
    assert r.status_code == 200
    name = r.get_json()['name']
    with tarfile.open(fileobj=io.BytesIO(client.get(f'/api/backup/{name}').data)) as tf:
        names = tf.getnames()
    assert 'data/keep.txt' in names
    assert 'data/shadow.db' not in names, '坏库不该被塞进包里冒充好数据'


def test_limit_bucket_exists():
    """连点十下会白占十份磁盘,得有 bucket 挡着。"""
    from extensions import auth
    assert 'backup' in auth._API_LIMITS


# === 与命令行脚本同源 ===

def test_shell_script_is_only_a_wrapper():
    """两份实现迟早会漂 —— 之前就有过。脚本必须只是壳。"""
    script = (Path(__file__).resolve().parent.parent / 'scripts' / 'backup.sh').read_text()
    assert 'extensions.backup' in script, 'backup.sh 绕过了 extensions/backup.py'
    assert 'tar --exclude' not in script, 'backup.sh 又自己实现了一遍打包'
    assert 'sqlite3' not in script, 'backup.sh 又自己实现了一遍快照'
