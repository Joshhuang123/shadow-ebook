"""数据层 guard: 所有 books.id 必须 ≤64 字符 (extensions/books.py:28 上限)。

跟 test_safe_book_path.py 互补:
  - test_safe_book_path.py 测 函数层 (is_valid_book_id 对 65 字符返回 False)
  - 本测试        测 数据层 (生产 DB 里不存在 >64 字符的 id)

未来任何 import 路径绕过 is_valid_book_id、或直接 SQL 改库,本测试会拦下。
CI 首次启动时 data/shadow.db 不存在,自动 skip,不挡 CI。
"""
import sqlite3
from pathlib import Path

import pytest

_DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'shadow.db'


def test_no_book_id_exceeds_64_chars():
    if not _DB_PATH.exists():
        pytest.skip("data/shadow.db 不存在 (CI / 全新 checkout)")
    with sqlite3.connect(str(_DB_PATH)) as conn:
        violations = [r[0] for r in conn.execute(
            "SELECT id FROM books WHERE LENGTH(id) > 64"
        )]
    assert not violations, (
        f"id 超 64 字符 (违反 extensions/books.py:28 上限): {violations[:3]}"
    )
