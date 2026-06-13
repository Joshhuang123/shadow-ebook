"""is_valid_book_id 是路径穿越的第一道防线 —— 这里测它对 14 个常见攻击串都拒绝。

正则: ^[a-zA-Z0-9_-]{1,64}$ (字母数字下划线连字符, 1-64 字符)
"""
import pytest

from extensions.books import is_valid_book_id


@pytest.mark.parametrize('book_id', [
    'abc',
    'abc-123',
    'a_b-c',
    'harry_potter_1',
    'A',                       # 单字符下界
    'A' * 64,                  # 64 字符上界
    'a1' * 32,                 # mix 至 64 字符
])
def test_valid_ids(book_id):
    assert is_valid_book_id(book_id) is True


@pytest.mark.parametrize('book_id', [
    '',                        # 空串
    None,                      # None
    'A' * 65,                  # 超过 64
    'ab/cd',                   # 任何 /
    '../../etc/passwd',        # 经典 path traversal
    '..\\..\\etc\\passwd',     # Windows path traversal
    'abc..def',                # 含 ..
    'abc def',                 # 空格
    'abc.txt',                 # 含点
    'abc;rm -rf /',            # shell 注入
    'abc\x00null',             # null byte (sqlite TEXT 列也不该接受)
    'abc%2F',                  # URL 编码绕过尝试
    '~/secret',                # ~ home expansion
    'a/b',                     # 任何 /
])
def test_invalid_ids(book_id):
    assert is_valid_book_id(book_id) is False
