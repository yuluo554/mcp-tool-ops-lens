"""模块 3 归因守门（M3 DoD 逐项落成可证伪断言）。

覆盖：
  · 五分类（timeout / permission_denied / invalid_args / content_refusal / other）
  · **K10 规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空
  · 未生效规则落 `other` 且**报告列出原因**（用 `rules.ineffective_patterns()`）
  · **只在 `error_text` 上匹配**：成功记录的正常输出会误命中宽模式（M1 实测）
  · `unknown` 不参与归因（未声明成败 ≠ 失败，K1）
  · 与植入真值逐 server 对账（失败模式维度）
  · 匹配面非空自证

变异验证（`tools/mutation_check.py`）：
  · 摘掉 `effective_patterns` 的门 → 本文件必红
  · 把未生效规则塞进计算路径 → 本文件必红
"""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from opslens import attribute  # noqa: E402
from opslens import config  # noqa: E402
from opslens import pipeline  # noqa: E402
from opslens import schema  # noqa: E402


@pytest.fixture(scope="module")
def truth():
    with open(os.path.join(SYNTHETIC_DIR, "truth.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def attr():
    rules = config.load_rules()
    events, _report = pipeline.scan_home(SYNTHETIC_DIR)
    return attribute.attribute(events, rules)


def _event(status, error_text, server="fake-server", tool="tool_a", seq=1):
    return schema.ToolCallEvent(
        source="claude_code",
        source_version="2.1.233",
        session_id="s",
        seq=seq,
        timestamp="2026-10-16T00:00:0{0}Z".format(seq),
        server=server,
        tool=tool,
        status=status,
        error_text=error_text,
    )


# ---------------------------------------------------------------------------
# 五分类
# ---------------------------------------------------------------------------


def test_five_categories_are_declared():
    rules = config.load_rules()
    events, _report = pipeline.scan_home(SYNTHETIC_DIR)
    payload = attribute.attribute(events, rules)
    assert payload["categories"] == [
        "timeout",
        "permission_denied",
        "invalid_args",
        "content_refusal",
        "other",
    ]


def test_by_category_covers_every_declared_category(attr):
    names = [item["category"] for item in attr["by_category"]]
    assert names == attr["categories"], "分类计数必须逐类列出（含计数为 0 的类）"


def test_each_failure_lands_in_exactly_one_category(attr):
    """每类计数之和 == 参与归因的失败总数（防重复计数或漏计）。"""
    total = sum(item["calls"] for item in attr["by_category"])
    assert total == attr["totals"]["calls_error"]


def test_only_error_events_participate(attr):
    """归因只消费 `status=error` 的事件（成功与 unknown 都不参与）。"""
    rules = config.load_rules()
    events = [
        _event(schema.STATUS_OK, "error: unexpected argument '-n' found", seq=1),
        _event(schema.STATUS_UNKNOWN, "Command timed out after 10m 0s", seq=2),
        _event(schema.STATUS_ERROR, "Command timed out after 10m 0s", seq=3),
    ]
    payload = attribute.attribute(events, rules)
    assert payload["totals"]["calls_error"] == 1, "成功或 unknown 记录混进了归因"
    counts = dict((item["category"], item["calls"]) for item in payload["by_category"])
    assert counts["timeout"] == 1, "唯一一条失败记录未被归为 timeout"


def test_unknown_with_error_text_is_not_attributed():
    """`unknown` 记录即便含错误文本也**不得**被归为失败类别（K1）。"""
    rules = config.load_rules()
    events = [_event(schema.STATUS_UNKNOWN, "PermissionError: [Errno 13] Permission denied", seq=1)]
    payload = attribute.attribute(events, rules)
    assert payload["totals"]["calls_error"] == 0
    assert all(item["calls"] == 0 for item in payload["by_category"])


def test_success_records_are_not_matched():
    """宽模式在成功记录的正常输出上会误命中（M1 实测）→ 成功记录不参与匹配。"""
    rules = config.load_rules()
    # 该文本实测会出现在 is_error=false 的记录里（工具的**正常输出**）
    events = [_event(schema.STATUS_OK, "error: unexpected argument '-n' found", seq=1)]
    payload = attribute.attribute(events, rules)
    assert payload["totals"]["calls_error"] == 0


# ---------------------------------------------------------------------------
# K10 规则门控双条件
# ---------------------------------------------------------------------------


def test_pending_rule_does_not_enter_computation_path(attr):
    """`F-REFUSE-1` 是 pending（本机 0 实测样例）→ 必须不生效。"""
    assert "F-REFUSE-1" not in attr["effective_rule_ids"]
    refuse = [item for item in attr["by_category"] if item["category"] == "content_refusal"]
    assert refuse, "分类表必须仍列出该类别（未生效 ≠ 类别不存在）"
    assert refuse[0]["calls"] == 0, "未生效规则覆盖的类别被计入命中"


def test_ineffective_rules_are_listed_with_reasons(attr):
    """未生效规则必须在产出里显式列出原因（plan/03 §3.2 硬门）。"""
    assert attr["ineffective_rules"], "本机实测存在 0 样例规则，未生效清单不应为空"
    for item in attr["ineffective_rules"]:
        assert item["reasons"], "未生效原因必须显式列出"
    ids = [item["id"] for item in attr["ineffective_rules"]]
    assert "F-REFUSE-1" in ids


def test_content_refusal_falls_to_other_when_rule_ineffective(tmp_out):
    """未生效规则所覆盖的类别：命中它的失败必须落 `other`（不得静默丢弃）。"""
    from opslens import serialize

    rules = config.load_rules()
    # 合成日志里 fake-low-fail 的 1 条内容拒绝文本
    events = [_event(schema.STATUS_ERROR, "I cannot assist with that request.", server="fake-low-fail")]
    payload = attribute.attribute(events, rules)
    assert payload["totals"]["other"] == 1, "未生效规则覆盖的失败未落 other"
    assert payload["totals"]["matched"] == 0


def test_rule_becomes_effective_only_with_both_gates_satisfied(tmp_out):
    """阳性对照 + 双门独立可证伪：两条门都满足时才生效。"""
    from opslens import serialize

    pack = [
        {
            "id": "P-PENDING-WITH-SAMPLES",
            "category": "timeout",
            "status": "pending",
            "patterns": ["boom"],
            "verified_samples": ["有样例但状态仍是待核对"],
        },
        {
            "id": "P-VERIFIED-NO-SAMPLES",
            "category": "timeout",
            "status": "verified",
            "patterns": ["boom"],
            "verified_samples": [],
        },
        {
            "id": "P-OK",
            "category": "timeout",
            "status": "verified",
            "patterns": ["boom"],
            "verified_samples": ["真实样例"],
        },
    ]
    serialize.write_json(os.path.join(tmp_out, "thresholds.json"), {"remove_candidate": {"failure_rate_gte": 0.5}})
    serialize.write_json(os.path.join(tmp_out, "params.json"), {"retry": {"window_seconds": 120}})
    serialize.write_json(
        os.path.join(tmp_out, "failure_patterns.json"),
        {"categories": ["timeout", "permission_denied", "invalid_args", "content_refusal", "other"], "rules": pack},
    )
    rules = config.load_rules(tmp_out)
    payload = attribute.attribute([_event(schema.STATUS_ERROR, "boom")], rules)
    assert payload["effective_rule_ids"] == ["P-OK"], "门控未拦下不合规规则"
    counts = dict((item["category"], item["calls"]) for item in payload["by_category"])
    assert counts["timeout"] == 1
    assert sorted(item["id"] for item in payload["ineffective_rules"]) == [
        "P-PENDING-WITH-SAMPLES",
        "P-VERIFIED-NO-SAMPLES",
    ]


def test_effective_rules_all_have_verified_samples(attr):
    rules = config.load_rules()
    by_id = dict((rule["id"], rule) for rule in rules.patterns["rules"])
    for rule_id in attr["effective_rule_ids"]:
        rule = by_id[rule_id]
        assert rule["status"] == config.STATUS_VERIFIED
        assert rule["verified_samples"], "{0} 无已核对样例却生效".format(rule_id)


# ---------------------------------------------------------------------------
# 与植入真值对账（失败模式维度）
# ---------------------------------------------------------------------------


def _expected_distribution(server_entry):
    """真值 → 期望分布（未生效规则覆盖的类别落 other）。"""
    expected = {}
    for mode, info in server_entry["failure_modes"].items():
        target = mode if info["rule_effective"] else attribute.CATEGORY_OTHER
        expected[target] = expected.get(target, 0) + info["calls"]
    return expected


def test_claude_failure_modes_reconcile_with_truth(attr, truth):
    by_server = dict(((item["source"], item["server"]), item) for item in attr["by_server"])
    checked = 0
    for server in truth["claude"]["servers"]:
        item = by_server[("claude_code", server["server"])]
        got = dict((category, calls) for category, calls in item["categories"].items() if calls)
        expected = _expected_distribution(server)
        assert got == expected, "{0} 归因分布与真值不符：{1} != {2}".format(server["server"], got, expected)
        checked += 1
    assert checked >= 6, "对账覆盖面过小（{0} 项）".format(checked)


def test_codex_failure_modes_reconcile_with_truth(attr, truth):
    by_server = dict(((item["source"], item["server"]), item) for item in attr["by_server"])
    item = by_server[("codex", "<codex>")]
    got = dict((category, calls) for category, calls in item["categories"].items() if calls)
    expected = _expected_distribution(truth["codex"])
    assert got == expected, "Codex 归因分布与真值不符：{0} != {1}".format(got, expected)


def test_timeout_rule_actually_matches_multiline_error_text(attr):
    """M3 修正的接口缺陷回归：`Command timed out after` 在第二行，必须能命中。"""
    timeout_hits = [item for item in attr["matched_patterns"] if item["rule_id"] == "F-TIMEOUT-1"]
    assert timeout_hits, "超时规则未命中任何记录（多行签名疑似又被首行截断）"
    patterns = set(item["pattern"] for item in timeout_hits)
    assert any("Command timed out after" in pattern for pattern in patterns), (
        "命中的是宽模式而非实测签名，多行归一可能失效：{0}".format(patterns)
    )


def test_matched_patterns_are_auditable(attr):
    """匹配到的规则/模式/计数必须可审计（模式表入库、可复核）。"""
    assert attr["matched_patterns"], "扫描面为空，断言可能空转"
    for item in attr["matched_patterns"]:
        assert item["rule_id"] and item["pattern"] and item["calls"] >= 1


def test_by_server_only_contains_error_calls(attr):
    """`by_server` 的 `calls_error` 必须与该 server 的归因分类计数之和一致。"""
    for item in attr["by_server"]:
        assert sum(item["categories"].values()) == item["calls_error"], item["server"]


# ---------------------------------------------------------------------------
# 确定性
# ---------------------------------------------------------------------------


def test_attribute_is_deterministic_on_double_run():
    rules = config.load_rules()
    events, _report = pipeline.scan_home(SYNTHETIC_DIR)
    first = json.dumps(attribute.attribute(events, rules), sort_keys=True, ensure_ascii=False)
    second = json.dumps(
        attribute.attribute(list(reversed(events)), rules), sort_keys=True, ensure_ascii=False
    )
    assert first == second, "归因结果依赖输入顺序（确定性被破坏）"


def test_attribution_scan_face_is_not_empty(attr):
    assert attr["totals"]["calls_error"] >= 1, "扫描面为空"
