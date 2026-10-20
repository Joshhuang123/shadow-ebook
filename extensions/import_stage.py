"""导入暂存区:预览一次、导入一次。

为什么要暂存
------------
「先预览目录、再导入」如果每次都重新上传文件,一个 50MB 的 PDF 在
局域网上要传两遍 —— 慢,而且没必要。家长点「预览」时文件已经传到
服务器了,那就把它放在那儿,导入时带一个 token 上来,服务端用暂存
的那份。

暂存区特性:
  * token 是随机的,不能猜
  * 过期自动清(默认 1 小时),不然磁盘会被撑爆
  * 只存原始字节,不存任何解析结果 —— 解析结果在预览时重算,
    保证「预览看到的」和「导进去的」是同一份逻辑跑出来的
  * 导入成功后立刻删掉暂存文件
"""
import json
import os
import secrets
import shutil
import time
from pathlib import Path

logger = __import__('logging').getLogger(__name__)

# 默认放在 data/import_stage —— 和 data/ 同级,跟着数据目录走
STAGE_DIR = Path(__file__).resolve().parent.parent / 'data' / 'import_stage'

# 暂存多久(秒)。家长预览完可能去干别的事,一小时够宽松了。
TTL_SECONDS = 3600

# 暂存区总大小上限(字节)。超了就先清过期���,还超就拒绝新的。
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def _ensure_dir() -> Path:
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    return STAGE_DIR


def _meta_path(token: str) -> Path:
    return _ensure_dir() / f'{token}.json'


def _data_path(token: str) -> Path:
    return _ensure_dir() / f'{token}.bin'


def _valid_token(token) -> bool:
    return isinstance(token, str) and 8 <= len(token) <= 64 and all(
        c.isalnum() or c in '-_' for c in token)


def cleanup_expired(now: float = None) -> int:
    """清掉过期的暂存文件,返回清掉几个。"""
    now = now or time.time()
    if not STAGE_DIR.exists():
        return 0
    removed = 0
    for meta in STAGE_DIR.glob('*.json'):
        try:
            info = json.loads(meta.read_text(encoding='utf-8'))
        except Exception:
            try:
                meta.unlink()
                removed += 1
            except OSError:
                pass
            continue
        if now - float(info.get('ts', 0)) > TTL_SECONDS:
            token = meta.stem
            for p in (meta, _data_path(token)):
                try:
                    p.unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def _total_bytes() -> int:
    if not STAGE_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in STAGE_DIR.glob('*.bin') if f.is_file())


def stage(raw: bytes, filename: str) -> str:
    """把上传的原始字节放进暂存区,返回 token。

    同一个文件重复预览会各拿一个 token —— 简单且不会互相踩。
    """
    cleanup_expired()
    _ensure_dir()
    if _total_bytes() + len(raw) > MAX_TOTAL_BYTES:
        # 腾一腾:把最老的清掉再来
        _purge_oldest(len(raw))
    if _total_bytes() + len(raw) > MAX_TOTAL_BYTES:
        raise RuntimeError('暂存区满了,请稍后再试(或少选几本)')

    token = secrets.token_urlsafe(18)
    _data_path(token).write_bytes(raw)
    _meta_path(token).write_text(json.dumps({
        'filename': filename or 'book',
        'size': len(raw),
        'ts': time.time(),
    }, ensure_ascii=False), encoding='utf-8')
    return token


def _purge_oldest(need: int) -> None:
    """按时间从老到新清,直到腾出 need 字节。"""
    if not STAGE_DIR.exists():
        return
    items = []
    for meta in STAGE_DIR.glob('*.json'):
        try:
            info = json.loads(meta.read_text(encoding='utf-8'))
            items.append((float(info.get('ts', 0)), meta.stem))
        except Exception:
            items.append((0, meta.stem))
    items.sort()
    freed = 0
    for _, token in items:
        for p in (_meta_path(token), _data_path(token)):
            try:
                freed += p.stat().st_size
                p.unlink()
            except OSError:
                pass
        if freed >= need:
            break


def get(token: str):
    """取暂存的 (raw, filename)。取不到返回 (None, None)。"""
    if not _valid_token(token):
        return None, None
    meta = _meta_path(token)
    data = _data_path(token)
    if not meta.exists() or not data.exists():
        return None, None
    try:
        info = json.loads(meta.read_text(encoding='utf-8'))
    except Exception:
        return None, None
    if time.time() - float(info.get('ts', 0)) > TTL_SECONDS:
        drop(token)
        return None, None
    try:
        return data.read_bytes(), info.get('filename') or 'book'
    except OSError:
        return None, None


def drop(token: str) -> None:
    """删掉一个暂存(导入成功后调用)。"""
    if not _valid_token(token):
        return
    for p in (_meta_path(token), _data_path(token)):
        try:
            p.unlink()
        except OSError:
            pass


def clear_all() -> None:
    """清空暂存区(家长页「清理」按钮 / 启动时调用)。"""
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR, ignore_errors=True)
    _ensure_dir()
