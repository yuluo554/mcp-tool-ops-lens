"""模块 3 · 失败模式归因（**规则匹配，非 AI 评分**）。

口径唯一出处：`plan/03 §3`（分类标签、规则表结构、归因产出）。本模块与
`aggregate.py` 是引擎侧**仅有的两处可含除法**的落点（口径唯一性守门见
`tests/test_aggregate.py`）。

硬门（K10，plan/03 §3.2）：`status == "verified"` **且** `verified_samples` 非空
的规则才进计算路径；未生效规则一律落 `other`，并**在产出里显式列出原因**
（用 `config.RuleSet.ineffective_patterns()`）。门控在 `config.effective_patterns()`
里落成一次，本模块只消费结果——**绝不在这里再写一份门控**（第二份口径即漂移源）。

匹配面纪律（`failure_patterns.json` 的 note 明写）：**只在 `error_text` 上匹配**。
宽模式（如 `\\bT?imeout...\\b`）会在成功记录的正常输出上误命中（本机实测：
`error: unexpected argument '-n' found` 出现在 `is_error=false` 的记录里）。
故 `status != "error"` 的事件一律不参与匹配——`unknown` 尤其不得被归因
（它是"未声明成败"，不是"失败"，K1）。

确定性纪律：纯函数式——按事件流的固定顺序匹配，不读时钟、不读随机、不写盘。
"""

import re

from . import schema

ATTRIBUTE_SCHEMA = "opslens.attribute/1"

# 未命中任何生效规则的失败一律落此类（plan/03 §3.1 五分类之末）
CATEGORY_OTHER = "other"


def _match_rule(error_text, rule):
    """在 `error_text` 上按规则的模式表依次匹配；返回命中的模式（无 → None）。

    模式一律以 `re.search` 语义解释（与 `failure_patterns.json` 的写法一致）。
    """
    for pattern in rule.get("patterns") or []:
        if re.search(pattern, error_text):
            return pattern
    return None


def _blank_distribution(categories):
    return dict((category, 0) for category in categories)


def attribute(events, rules):
    """事件流 + 规则包 → 归因载荷（`plan/03 §3.3`）。

    只对 `status == "error"` 的事件做匹配（见模块 docstring 的匹配面纪律）。
    每类计数 + 未命中（落 `other`）计数单列；未生效规则连同原因显式列出。
    """
    categories = list(rules.patterns.get("categories") or [])
    effective = rules.effective_patterns()
    effective_ids = [rule.get("id") for rule in effective]

    by_category = dict((category, 0) for category in categories)
    by_category.setdefault(CATEGORY_OTHER, 0)
    pattern_hits = {}  # (rule_id, pattern) -> 命中次数
    by_server = {}  # (source, server) -> 分布
    error_calls = 0

    for event in events:
        if event.status != schema.STATUS_ERROR:
            # 成功与 unknown 都不参与归因：成功记录的正常输出会误命中宽模式，
            # unknown 是"未声明成败"而非失败（K1）。
            continue
        error_calls += 1
        category = CATEGORY_OTHER
        rule_id = None
        matched_pattern = None
        for rule in effective:
            hit = _match_rule(event.error_text, rule)
            if hit is not None:
                category = rule.get("category") or CATEGORY_OTHER
                rule_id = rule.get("id")
                matched_pattern = hit
                pattern_hits[(rule_id, hit)] = pattern_hits.get((rule_id, hit), 0) + 1
                break
        by_category[category] = by_category.get(category, 0) + 1

        key = (event.source, event.server)
        bucket = by_server.setdefault(
            key,
            {
                "source": event.source,
                "server": event.server,
                "calls_error": 0,
                "categories": _blank_distribution(categories),
            },
        )
        bucket["calls_error"] += 1
        bucket["categories"][category] = bucket["categories"].get(category, 0) + 1

    matched = error_calls - by_category.get(CATEGORY_OTHER, 0)

    return {
        "schema": ATTRIBUTE_SCHEMA,
        "categories": categories,
        "effective_rule_ids": effective_ids,
        # 未生效规则 + 原因：报告"未生效规则"节的唯一数据来源（plan/03 §3.2 硬门）
        "ineffective_rules": rules.ineffective_patterns(),
        "totals": {
            "calls_error": error_calls,
            "matched": matched,
            CATEGORY_OTHER: by_category.get(CATEGORY_OTHER, 0),
            "unmatched_note": (
                "落 other 的失败 = 未命中任何生效规则（含被门控拦下的规则所覆盖的类别）"
                "，未生效原因见 ineffective_rules"
            ),
        },
        "by_category": [
            {"category": category, "calls": by_category.get(category, 0)} for category in categories
        ],
        "by_server": [by_server[key] for key in sorted(by_server)],
        "matched_patterns": [
            {
                "rule_id": rule_id,
                "pattern": pattern,
                "calls": count,
            }
            for (rule_id, pattern), count in sorted(pattern_hits.items())
        ],
        "coverage_note": (
            "归因只在失败记录（status=error）的 error_text 上匹配；"
            "status=unknown 的记录不参与归因（未声明成败 ≠ 失败）；"
            "未生效规则（status≠verified 或 verified_samples 为空）不参与匹配，其覆盖的类别落 other。"
        ),
    }
