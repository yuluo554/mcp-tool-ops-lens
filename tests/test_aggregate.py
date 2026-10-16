"""模块 2 聚合守门（M3 DoD 逐项落成可证伪断言）。

覆盖：
  · 指标按 `plan/03 §2.1` 逐项实现（server / tool 两级）
  · **对账等式**：`calls_ok + calls_error + calls_unknown == calls_total`（两级 + 汇总）
  · `failure_rate` 分母**不含 unknown**；分母为 0 → `null` + `insufficient_data`
  · token 四项分列 + `token_samples` / `token_missing` 单列 + `turn_` 前缀
  · 耗时：Claude 侧 `null` + `duration_available=false`
  · 两级都输出 `unknown` 计数
  · `retry_count` 窗口值来自 `params.json`（不写死）
  · **与植入真值逐 server 对账**（比"能跑"强得多）
  · **口径唯一性守门**：`BinOp(Div)` 只允许出现在聚合层 / 归因层 / 基准生成器 / `tests/`

变异验证（`tools/mutation_check.py`）：
  · 把 unknown 计入失败率分母 → 本文件必红
  · 把 `BinOp(Div)` 挪进报告层 / CLI 层 → 口径唯一性守门必红
"""

import ast
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
OPSLENS_DIR = os.path.join(SRC_DIR, "opslens")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from opslens import aggregate  # noqa: E402
from opslens import config  # noqa: E402
from opslens import pipeline  # noqa: E402
from opslens import schema  # noqa: E402


@pytest.fixture(scope="module")
def truth():
    with open(os.path.join(SYNTHETIC_DIR, "truth.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def agg():
    rules = config.load_rules()
    events, _report = pipeline.scan_home(SYNTHETIC_DIR)
    return aggregate.aggregate(events, rules)


def _by_server(agg_payload):
    return dict(((row["source"], row["server"]), row) for row in agg_payload["server_level"])


# ---------------------------------------------------------------------------
# 对账等式（plan/03 §2.1 硬约束）
# ---------------------------------------------------------------------------


def test_accounting_identity_holds_at_server_level(agg):
    assert agg["server_level"], "扫描面为空，断言可能空转"
    for row in agg["server_level"]:
        assert row["calls_ok"] + row["calls_error"] + row["calls_unknown"] == row["calls_total"], row


def test_accounting_identity_holds_at_tool_level(agg):
    assert agg["tool_level"], "扫描面为空"
    for row in agg["tool_level"]:
        assert row["calls_ok"] + row["calls_error"] + row["calls_unknown"] == row["calls_total"], row


def test_accounting_identity_holds_at_totals(agg):
    totals = agg["totals"]
    assert totals["calls_ok"] + totals["calls_error"] + totals["calls_unknown"] == totals["calls_total"]
    assert totals["calls_total"] == sum(row["calls_total"] for row in agg["server_level"])


def test_accounting_identity_breaks_are_detected():
    """探针自证：对账等式被打破时必须抛错（否则上面三条是假门）。"""
    # 手工构造一行"三态之和 != 总数"的聚合行 → `_finish_row` 必须拒绝
    row = {
        "source": "claude_code",
        "server": "fake-server",
        "tool": "tool_a",
        "calls_total": 5,
        "calls_ok": 1,
        "calls_error": 1,
        "calls_unknown": 1,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_cache_read": 0,
        "tokens_cache_creation": 0,
        "token_samples": 0,
        "token_missing": 0,
        "duration_sum": 0,
        "duration_samples": 0,
        "duration_missing": 0,
    }
    with pytest.raises(AssertionError):
        aggregate._finish_row(row, 6, 0, "server")
    # 阳性对照：等式成立时不得抛错（否则上面是空转）
    good = dict(row, calls_total=3)
    assert aggregate._finish_row(good, 6, 0, "server")["calls_total"] == 3


# ---------------------------------------------------------------------------
# failure_rate：分母不含 unknown（K1）
# ---------------------------------------------------------------------------


def test_failure_rate_denominator_excludes_unknown(agg):
    """分母 = ok + error，**不含 unknown**（data/README §五 A / K1）。"""
    for row in agg["server_level"]:
        assert row["failure_rate_denominator"] == row["calls_ok"] + row["calls_error"], row
        assert row["failure_rate_numerator"] == row["calls_error"], row


def test_failure_rate_matches_truth_per_server(agg, truth):
    """逐 server 与植入真值对账（含 unknown 的 server 最能暴露分母口径错误）。"""
    by_server = _by_server(agg)
    saw_unknown = False
    for server in truth["claude"]["servers"]:
        row = by_server[("claude_code", server["server"])]
        assert row["failure_rate"] == server["expected_failure_rate"], server["server"]
        if server["calls_unknown"]:
            saw_unknown = True
    assert saw_unknown, "真值里必须有带 unknown 的 server，否则本断言没演练到分母口径"


def test_failure_rate_would_differ_if_unknown_were_counted(agg):
    """可证伪自证：把 unknown 计入分母会得到**不同**的值（否则该守门是空转）。

    这正是变异项"unknown 计入失败率分母 → 必红"能生效的前提。
    """
    checked = 0
    for row in agg["server_level"]:
        if not row["calls_unknown"]:
            continue
        checked += 1
        wrong_denominator = row["calls_ok"] + row["calls_error"] + row["calls_unknown"]
        wrong = round(float(row["calls_error"]) / wrong_denominator, agg["rate_precision"])
        assert wrong != row["failure_rate"], "{0} 的分母口径无法被区分，守门无效".format(row["server"])
    assert checked >= 1, "没有带 unknown 的 server，本断言可能空转"


def test_zero_denominator_yields_null_and_insufficient_data():
    """分母为 0 → `null` + `insufficient_data=true`（不是 0，也不是 1）。"""
    rules = config.load_rules()
    events = [
        schema.ToolCallEvent(
            source="claude_code",
            source_version="2.1.233",
            session_id="s",
            seq=index,
            timestamp="2026-10-16T00:00:0{0}Z".format(index),
            server="fake-only-unknown",
            tool="tool_a",
            status="unknown",
        )
        for index in range(1, 4)
    ]
    payload = aggregate.aggregate(events, rules)
    row = payload["server_level"][0]
    assert row["calls_total"] == 3
    assert row["calls_unknown"] == 3
    assert row["failure_rate"] is None, "分母为 0 时失败率必须是 null，不是 0"
    assert row["insufficient_data"] is True
    assert row["failure_rate_denominator"] == 0


def test_unknown_is_reported_at_both_levels(agg):
    """两级维度都必须输出 unknown 计数（"未声明"不得看起来像"没问题"）。"""
    assert any(row["calls_unknown"] for row in agg["server_level"])
    assert any(row["calls_unknown"] for row in agg["tool_level"])


# ---------------------------------------------------------------------------
# token（K2 / K3）
# ---------------------------------------------------------------------------


def test_token_fields_are_four_separate_columns(agg):
    for row in agg["server_level"]:
        for key in ("tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation"):
            assert key in row, "token 四项必须分列（不合并）"
        assert "tokens_total" not in row, "合并出的总量列会重复计数缓存（D9 已弃）"


def test_token_samples_and_missing_are_single_columns(agg):
    for row in agg["server_level"]:
        assert row["token_samples"] + row["token_missing"] == row["calls_total"], row


def test_turn_token_avg_uses_turn_prefix_and_denominator_is_samples(agg):
    """均值名带 `turn_` 前缀（明确"轮次归属"），分母是 `token_samples`。"""
    for row in agg["server_level"]:
        if row["token_samples"] == 0:
            assert row["turn_token_avg"] is None, "无样本时均值必须是 null（不是 0）"
            continue
        token_sum = (
            row["tokens_input"]
            + row["tokens_output"]
            + row["tokens_cache_read"]
            + row["tokens_cache_creation"]
        )
        expected = round(float(token_sum) / row["token_samples"], agg["rate_precision"])
        assert row["turn_token_avg"] == expected, row


def test_codex_tokens_are_not_attributed_to_calls(agg):
    """K3：Codex 侧 token 不可按工具归因 → `token_samples=0`（不是"零开销"）。"""
    codex = [row for row in agg["server_level"] if row["source"] == schema.SOURCE_CODEX]
    assert codex, "合成数据必须含 Codex 侧"
    for row in codex:
        assert row["token_samples"] == 0
        assert row["token_missing"] == row["calls_total"]
        assert row["turn_token_avg"] is None


# ---------------------------------------------------------------------------
# 耗时（K4）
# ---------------------------------------------------------------------------


def test_claude_duration_is_unavailable_not_zero(agg):
    """Claude 侧按工具耗时不可得 → `null` + `duration_available=false`（K4）。"""
    claude = [row for row in agg["server_level"] if row["source"] == schema.SOURCE_CLAUDE_CODE]
    assert claude, "扫描面为空"
    for row in claude:
        assert row["duration_avg_ms"] is None, "不可得的耗时必须是 null，不是 0"
        assert row["duration_available"] is False
        assert row["duration_samples"] == 0


def test_codex_duration_is_available_from_wall_time(agg):
    """阳性对照：Codex 侧 `Wall time` 可得 → 样本非空、均值非 null。"""
    codex = [row for row in agg["server_level"] if row["source"] == schema.SOURCE_CODEX]
    assert any(row["duration_available"] for row in codex), "Codex 侧耗时通路未被演练"


def test_duration_not_mixed_across_sources(agg):
    """两侧口径不同源，**不混算均值**：Claude 侧样本恒为 0。"""
    claude_samples = sum(
        row["duration_samples"] for row in agg["server_level"] if row["source"] == schema.SOURCE_CLAUDE_CODE
    )
    assert claude_samples == 0


# ---------------------------------------------------------------------------
# 重试识别（窗口值来自规则包）
# ---------------------------------------------------------------------------


def test_retry_window_comes_from_params_not_hardcoded(agg):
    rules = config.load_rules()
    assert agg["retry_window_seconds"] == rules.params["retry"]["window_seconds"]


def test_retry_count_matches_truth_per_server(agg, truth):
    """`expected_retry_count` 必须能由日志按窗口规则复算（M3 修正的 M1 缺陷）。"""
    by_server = _by_server(agg)
    for server in truth["claude"]["servers"]:
        row = by_server[("claude_code", server["server"])]
        assert row["retry_count"] == server["expected_retry_count"], server["server"]


def test_retry_window_change_changes_the_count(tmp_out):
    """窗口值是真参数（不写死）：改小窗口 → 重试数必须变化（否则它是硬编码常量）。"""
    from opslens import serialize

    rules = config.load_rules()
    events, _report = pipeline.scan_home(SYNTHETIC_DIR)
    baseline = aggregate.aggregate(events, rules)["totals"]["retry_count"]

    params = dict(rules.params)
    params["retry"] = dict(params["retry"], window_seconds=0)
    serialize.write_json(os.path.join(tmp_out, "thresholds.json"), rules.thresholds)
    serialize.write_json(os.path.join(tmp_out, "params.json"), params)
    serialize.write_json(os.path.join(tmp_out, "failure_patterns.json"), rules.patterns)

    narrow = aggregate.aggregate(events, config.load_rules(tmp_out))
    assert narrow["totals"]["retry_count"] < baseline, "窗口参数未生效（疑似写死）"


# ---------------------------------------------------------------------------
# 两级维度与确定性
# ---------------------------------------------------------------------------


def test_both_levels_present_and_tool_level_is_finer(agg):
    assert agg["server_level"] and agg["tool_level"]
    assert len(agg["tool_level"]) >= len(agg["server_level"])
    for row in agg["tool_level"]:
        assert row["level"] == "tool" and row["tool"]
    for row in agg["server_level"]:
        assert row["level"] == "server" and "tool" not in row


def test_aggregate_is_deterministic_on_double_run():
    rules = config.load_rules()
    events, _report = pipeline.scan_home(SYNTHETIC_DIR)
    first = json.dumps(aggregate.aggregate(events, rules), sort_keys=True, ensure_ascii=False)
    second = json.dumps(aggregate.aggregate(list(reversed(events)), rules), sort_keys=True, ensure_ascii=False)
    assert first == second, "聚合结果依赖输入顺序（确定性被破坏）"


def test_totals_match_manifest_declared_totals(agg):
    with open(os.path.join(SYNTHETIC_DIR, "manifest.json"), "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    assert agg["totals"]["calls_total"] == manifest["totals"]["calls_total"]
    assert agg["totals"]["calls_ok"] == manifest["coverage"][2]["items"][0]["sampled_calls"]
    assert agg["totals"]["calls_error"] == manifest["coverage"][2]["items"][1]["sampled_calls"]
    assert agg["totals"]["calls_unknown"] == manifest["coverage"][2]["items"][2]["sampled_calls"]


# ---------------------------------------------------------------------------
# 时间戳换算（纯整数、不读时钟）
# ---------------------------------------------------------------------------


def test_timestamp_to_seconds_handles_offsets_and_fractions():
    base = aggregate.timestamp_to_seconds("2026-10-16T00:00:00Z")
    assert base is not None
    assert aggregate.timestamp_to_seconds("2026-10-16T00:00:01.500Z") == base + 1
    assert aggregate.timestamp_to_seconds("2026-10-16T01:00:00+01:00") == base
    assert aggregate.timestamp_to_seconds("2026-10-16T00:00:00-01:00") == base + 3600


def test_timestamp_to_seconds_rejects_unparseable():
    assert aggregate.timestamp_to_seconds("") is None
    assert aggregate.timestamp_to_seconds("T0") is None
    assert aggregate.timestamp_to_seconds(None) is None


def test_timestamp_conversion_is_leap_year_correct():
    """闰年规则完整：2024-02-29 与 2024-03-01 相差一天。"""
    a = aggregate.timestamp_to_seconds("2024-02-29T00:00:00Z")
    b = aggregate.timestamp_to_seconds("2024-03-01T00:00:00Z")
    assert b - a == 86400


# ---------------------------------------------------------------------------
# 口径唯一性守门：`BinOp(Div)` 只准出现在聚合层 / 归因层 / 生成器 / tests
# ---------------------------------------------------------------------------

# 允许出现除法运算的落点（相对仓库根，正斜杠）。理由逐条：
#   · src/opslens/aggregate.py —— 模块 2 的比率/均值（口径表 plan/03 §2.1）
#   · src/opslens/attribute.py —— 模块 3 的归因统计（若出现比率）
#   · tools/gen_synthetic_logs.py —— 真值**期望值**推导，必须与引擎相互独立
#     （让两者共用实现会让真值沦为"引擎自证"，K12 明禁）
DIV_ALLOWED_FILES = frozenset(
    [
        "src/opslens/aggregate.py",
        "src/opslens/attribute.py",
        "tools/gen_synthetic_logs.py",
    ]
)

DIV_SCAN_DIRS = ("src", "tools")


def _div_offenders():
    """扫 `src/` 与 `tools/`，返回出现 `BinOp(Div)` 的非白名单文件。"""
    offenders = []
    scanned = 0
    for directory in DIV_SCAN_DIRS:
        root = os.path.join(REPO_ROOT, directory)
        for dirpath, _dirnames, filenames in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(filenames):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, REPO_ROOT).replace("\\", "/")
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
                scanned += 1
                if rel in DIV_ALLOWED_FILES:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                        offenders.append("{0}:{1}".format(rel, node.lineno))
    return offenders, scanned


def test_division_scan_face_is_not_empty():
    """扫描面非空自证：防"目录写错 → 扫 0 个 → 永远绿"。"""
    _offenders, scanned = _div_offenders()
    assert scanned >= 10, "口径唯一性扫描面只有 {0} 个文件".format(scanned)


def test_binop_div_only_in_aggregate_and_attribute_and_generator():
    """口径唯一性（plan/03 §2.3）：除法只出现在聚合层 / 归因层 / 真值生成器。

    防"报告层或 CLI 层出现第二份比率计算"——那是"数值口径不一致"的直接来源。
    """
    offenders, _scanned = _div_offenders()
    assert offenders == [], "除法运算出现在白名单之外：{0}".format(offenders)


def test_div_detector_actually_detects():
    """探针自证：给出含除法的样例源码，检测逻辑必须命中（否则守门是假门）。"""
    sample = "rate = numerator / denominator\n"
    tree = ast.parse(sample)
    hit = any(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) for node in ast.walk(tree))
    assert hit, "探针漏判了除法样例"


def test_aggregate_source_has_no_duplicated_rate_constant():
    """比率精度只来自规则包（K9）：聚合层源码不得出现精度数值字面量。"""
    rules = config.load_rules()
    precision = rules.params["rate_precision"]
    source = open(os.path.join(OPSLENS_DIR, "aggregate.py"), "r", encoding="utf-8").read()
    assert "round(float" in source, "聚合层的比率计算未走统一落点"
    # 精度必须经参数传入，不在源码里写死（此处按"未出现该字面量赋值"断言）
    assert "precision = {0}".format(precision) not in source
