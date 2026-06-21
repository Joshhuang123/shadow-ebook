"""courses.py 端点的基础覆盖 + R10 新加的限流。

之前 courses 是零测试, 加新限流后更必须有 CI 守护。
"""
import importlib

import pytest


@pytest.fixture
def client(tmp_db, clear_api_rate):
    import app as app_module
    importlib.reload(app_module)
    return app_module.app.test_client()


# === 内容端点 ===

def test_get_course_returns_full_content(client):
    r = client.get('/api/course')
    assert r.status_code == 200
    assert r.json['success'] is True
    assert 'units' in r.json['course']
    assert len(r.json['course']['units']) > 0


def test_get_unit_valid_index(client):
    r = client.get('/api/unit/0')
    assert r.status_code == 200
    assert 'unit' in r.json
    assert 'sentences' in r.json['unit']


def test_get_unit_invalid_index_returns_error(client):
    r = client.get('/api/unit/999')
    assert r.status_code == 200  # 注: 当前实现走 200+success:false, 跟项目其他端点一致
    assert r.json['success'] is False
    assert '不存在' in r.json['error']


def test_get_sentences_valid(client):
    r = client.get('/api/sentences/0')
    assert r.status_code == 200
    assert 'sentences' in r.json
    assert isinstance(r.json['sentences'], list)


def test_get_question_valid_topic(client):
    r = client.get('/api/question/现在进行时')
    assert r.status_code == 200
    assert 'question' in r.json
    assert 'options' in r.json['question']


def test_get_question_unknown_topic_returns_error(client):
    r = client.get('/api/question/不存在的语法点')
    assert r.status_code == 200
    assert r.json['success'] is False


# === R10: 全局限流守护 ===

def test_courses_rate_limited(client):
    """global bucket 满 → 4 个端点都 429。直接打 global 桶 (courses 用的是这个)。"""
    from extensions import auth
    with auth._API_LOCK:
        auth._API_RATE[('127.0.0.1', 'global')] = [9999999999.0] * 1000

    for url in ['/api/course', '/api/unit/0', '/api/sentences/0', '/api/question/现在进行时']:
        r = client.get(url)
        assert r.status_code == 429, f'{url} 应该 429, 实际 {r.status_code}'
        assert '请求过快' in r.json['error']
