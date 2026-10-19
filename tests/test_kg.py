"""知识图谱的测试。

重点不是「查出来对不对」,是**结构性不变量**:
  - 前置图必须无环(有环的话 learning_path 的 depth 会递归爆栈)
  - 每条 requires 边指向的节点都得存在(拼错 key 会静默产生一条悬空边)
  - 24 个语法点一个都不能少(少一个就意味着少教一个知识点)
"""
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from extensions.kg import (  # noqa: E402
    GRAMMAR_NODES, GRAMMAR_PREREQS, WORD_GRAMMAR_RULES,
)


EXPECTED_KEYS = {
    # KET
    'ket-pronouns', 'ket-there-be', 'ket-present-simple',
    'ket-present-continuous', 'ket-simple-past', 'ket-modals',
    'ket-imperative', 'ket-prepositions', 'ket-possessive',
    'ket-comparatives', 'ket-frequency', 'ket-future-going-to',
    # PET
    'pet-quantifiers', 'pet-conjunctions', 'pet-gerund-infinitive',
    'pet-used-to', 'pet-present-perfect', 'pet-past-perfect',
    'pet-modals-perfect', 'pet-passive', 'pet-relatives',
    'pet-conditional', 'pet-adverb-clauses', 'pet-reported-speech',
}


def _detect_cycle():
    """返回造成环的那个节点;无环返回 None。"""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in GRAMMAR_NODES}

    def visit(node, stack):
        color[node] = GREY
        for nxt in GRAMMAR_PREREQS.get(node, []):
            if color.get(nxt) == GREY:
                return nxt
            if color.get(nxt) == WHITE:
                found = visit(nxt, stack + [nxt])
                if found:
                    return found
        color[node] = BLACK
        return None

    for k in GRAMMAR_NODES:
        if color[k] == WHITE:
            found = visit(k, [])
            if found:
                return found
    return None


class TestGrammarSeeds:
    def test_cover_every_expected_point(self):
        assert set(GRAMMAR_NODES) == EXPECTED_KEYS, (
            '语法点集合变了:多出 '
            f'{set(GRAMMAR_NODES) - EXPECTED_KEYS},'
            f'缺少 {EXPECTED_KEYS - set(GRAMMAR_NODES)}'
        )

    def test_no_cycle(self):
        """前置图必须是有向无环图,否则 learning_path 会无限递归。"""
        cycle = _detect_cycle()
        assert cycle is None, f'前置图有环,经过 {cycle}'

    def test_no_dangling_edges(self):
        """requires 指向的必须都是真实存在的语法点。"""
        for dst, srcs in GRAMMAR_PREREQS.items():
            assert dst in GRAMMAR_NODES, f'{dst} 没在 GRAMMAR_NODES 里定义'
            for src in srcs:
                assert src in GRAMMAR_NODES, (
                    f'{dst} 依赖了不存在的 {src}(拼错了?)'
                )

    def test_no_self_loop(self):
        for dst, srcs in GRAMMAR_PREREQS.items():
            assert dst not in srcs, f'{dst} 依赖了自己'

    def test_no_duplicate_edges(self):
        for dst, srcs in GRAMMAR_PREREQS.items():
            assert len(srcs) == len(set(srcs)), f'{dst} 的前置里有重复'

    def test_pet_builds_on_ket_not_reverse(self):
        """方向只能是 KET → PET:PET 点可以依赖 KET 点(KET 是地基),
        但 KET 点绝不能依赖 PET 点,否则会出现「学 PET 才能学 KET」的环。"""
        for dst, srcs in GRAMMAR_PREREQS.items():
            if dst.startswith('ket-'):
                for src in srcs:
                    assert not src.startswith('pet-'), (
                        f'KET 点 {dst} 依赖了 PET 点 {src} —— '
                        '方向反了,KET 是 PET 的地基'
                    )

    def test_pet_actually_uses_ket_prereqs(self):
        """反向检查:至少有几条 PET→KET 的边,否则说明图根本没串起来。"""
        cross = [
            (dst, src) for dst, srcs in GRAMMAR_PREREQS.items()
            for src in srcs
            if dst.startswith('pet-') and src.startswith('ket-')
        ]
        assert len(cross) >= 5, 'PET 几乎不依赖 KET,图退化成两座孤岛'

    def test_levels_match_prefix(self):
        for key, (_title, level) in GRAMMAR_NODES.items():
            if key.startswith('ket-'):
                assert level == 1, f'{key} 是 KET,level 应为 1'
            else:
                assert level == 2, f'{key} 是 PET,level 应为 2'


class TestWordRules:
    def test_rules_point_to_real_grammar_keys(self):
        import re
        for pattern, gkey in WORD_GRAMMAR_RULES:
            assert gkey in GRAMMAR_NODES, (
                f'规则 {pattern!r} 指向不存在的语法点 {gkey}'
            )
            re.compile(pattern)   # 语法错误会在构建时才炸,这里提前拦

    def test_rules_are_compiled_once(self):
        import re
        compiled = [(re.compile(p), g) for p, g in WORD_GRAMMAR_RULES]
        assert len(compiled) == len(WORD_GRAMMAR_RULES)


class TestDepth:
    """learning_path 依赖 depth;这里把它的递归单独测一遍。"""

    def test_depth_finite_and_ordered(self):
        memo = {}

        def depth(key, seen=frozenset()):
            if key in seen:
                return 0          # 防环兜底,和无环测试互为保险
            if key in memo:
                return memo[key]
            seen = seen | {key}
            ps = GRAMMAR_PREREQS.get(key) or []
            memo[key] = 0 if not ps else 1 + max(depth(p, seen) for p in ps)
            return memo[key]

        depths = {k: depth(k) for k in GRAMMAR_NODES}
        assert all(isinstance(v, int) and v >= 0 for v in depths.values())
        # 有前置的点深度一定比它的前置深
        for dst, srcs in GRAMMAR_PREREQS.items():
            for src in srcs:
                assert depths[dst] > depths[src], (
                    f'{dst} 深度 {depths[dst]} 应大于前置 {src} 的 {depths[src]}'
                )

    def test_roots_have_depth_zero(self):
        """没有前置的点才是入口。注意用 .get:GRAMMAR_PREREQS 里只登记了
        「有前置的」和「显式空的」,没登记的 KET 点本身就是根。"""
        roots = [k for k in GRAMMAR_NODES if not GRAMMAR_PREREQS.get(k)]
        assert len(roots) >= 6, (
            f'起点只有 {len(roots)} 个({roots}),图退化成了链,'
            '孩子会感觉「必须按顺序从头来」'
        )


# ============================================================================
# 外部导入层(os-taxonomy 的 English 子图)
# 这些测试在没有跑过 import_os_taxonomy.py 的机器上会自动跳过,
# 不让 CI 因为一个可选数据源而红。
# ============================================================================
def _skill_nodes():
    from extensions.db import get_db, init_db
    init_db()
    return get_db().execute(
        "SELECT id, attrs FROM kg_node WHERE kind='skill'"
    ).fetchall()


_SKILLS = _skill_nodes()
needs_import = pytest.mark.skipif(
    not _SKILLS, reason='未跑 scripts/import_os_taxonomy.py,跳过外部数据层测试'
)


@needs_import
class TestSkillLayer:
    def test_nodes_carry_required_attrs(self):
        import json
        for row in _SKILLS:
            a = json.loads(row['attrs'])
            for key in ('domain', 'age_start', 'age_end', 'source'):
                assert key in a, f'{row["id"]} 缺字段 {key}'
            assert a['age_start'] <= a['age_end'], f'{row["id"]} 年龄区间反了'
            assert a['source'] == 'os-taxonomy-v1'

    def test_levels_within_range(self):
        from extensions.db import get_db, init_db
        init_db()
        bad = get_db().execute(
            "SELECT id, level FROM kg_node WHERE kind='skill' "
            'AND (level IS NULL OR level < 1 OR level > 5)'
        ).fetchall()
        assert not bad, f'level 越界: {[tuple(r) for r in bad]}'

    def test_no_dangling_skill_edges(self):
        from extensions.db import get_db, init_db
        init_db()
        db = get_db()
        n = db.execute(
            '''SELECT COUNT(*) c FROM kg_edge
               WHERE src LIKE 'skill:%'
                 AND (src NOT IN (SELECT id FROM kg_node)
                   OR dst NOT IN (SELECT id FROM kg_node))'''
        ).fetchone()['c']
        assert n == 0, f'{n} 条 skill 边指向不存在的节点'

    def test_skill_graph_acyclic(self):
        import collections
        from extensions.db import get_db, init_db
        init_db()
        g = collections.defaultdict(list)
        for r in get_db().execute(
                "SELECT src, dst FROM kg_edge WHERE rel='requires' "
                "AND src LIKE 'skill:%'"):
            g[r['src']].append(r['dst'])

        WHITE, GREY, BLACK = 0, 1, 2
        color = collections.defaultdict(int)

        def visit(n):
            color[n] = GREY
            for m in g.get(n, ()):
                if color[m] == GREY:
                    return m
                if color[m] == WHITE:
                    r = visit(m)
                    if r:
                        return r
            color[n] = BLACK
            return None

        for n in list(g):
            if color[n] == WHITE:
                cyc = visit(n)
                assert cyc is None, f'skill 子图有环,经过 {cyc}'

    def test_hard_edges_outweigh_soft(self):
        from extensions.db import get_db, init_db
        init_db()
        db = get_db()
        hard = db.execute(
            "SELECT COUNT(*) c FROM kg_edge WHERE src LIKE 'skill:%' "
            'AND weight >= 1.0').fetchone()['c']
        soft = db.execute(
            "SELECT COUNT(*) c FROM kg_edge WHERE src LIKE 'skill:%' "
            'AND weight < 1.0').fetchone()['c']
        assert hard > 0 and soft > 0, '硬/软前置应同时存在,否则权重没生效'
        assert hard > soft, f'硬前置应多于软前置:{hard} vs {soft}'

    def test_skills_by_age_respects_range(self):
        from extensions.kg import skills_by_age
        for age in (7, 10, 13):
            for s in skills_by_age(age=age, limit=200):
                a = s['attrs']
                assert a['age_start'] <= age <= a['age_end'], (
                    f'{s["label"]} 区间 {a["age_start"]}-{a["age_end"]} '
                    f'不含 {age} 岁'
                )

    def test_every_prereq_has_a_reason(self):
        """reason 是这层的核心价值(给家长解释「为什么卡在这」),不能空。"""
        from extensions.db import get_db, init_db
        init_db()
        n = get_db().execute(
            "SELECT COUNT(*) c FROM kg_edge WHERE src LIKE 'skill:%' "
            "AND (reason IS NULL OR TRIM(reason) = '')").fetchone()['c']
        assert n == 0, f'{n} 条 skill 边没有写理由'
