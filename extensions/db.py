"""
Owns: SQLite helpers (Phase 3) + shared file utilities used by Phase 1 modules.
Does NOT own: domain logic (each module owns its own data access patterns).

Phase 1 status: skeleton. `_safe_write_json` is a transitional helper — both
books.py and parent_data.py call it for atomic JSON writes. Will be removed
in Phase 3 when both migrate to SQLite.
"""
import json
import os
import secrets
from pathlib import Path


def _safe_write_json(path: Path, data):
    """原子写 JSON: 写 .tmp + fsync + rename, 防止并发写半截 / 崩溃残留。
    POSIX 上 rename 是原子的,读者要么看到旧内容要么看到新内容,不会看到中间状态。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f'.tmp.{os.getpid()}.{secrets.token_hex(4)}')
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())  # 强制落盘,防断电留半截
        os.replace(tmp_path, path)  # 原子 rename
    except Exception:
        # 清理残留 tmp
        try: tmp_path.unlink()
        except OSError: pass
        raise


def register_routes(app):
    """db 模块没有 HTTP 路由,只是被其他模块 import 共享 helper。"""
    pass