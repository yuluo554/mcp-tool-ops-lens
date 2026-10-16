"""模块 4 报告层守门（M5 DoD 逐项落成可证伪断言）。

覆盖：
  · **单一渲染源**：MD/HTML 都由 `report.json` 渲染 → 两格式内容一致是**结构性质**
  · **渲染层零判定**（AST 守门）：`report/` 无 `BinOp(Div)`、不 import 聚合层/归因层/规则包
  · **无外链硬断言**：渲染出口**常驻** `assert_no_external_resources`（不只测试里验一次）
  · 报告必含五节：来源与覆盖声明 / unknown 独立分区 / 建议附口径+阈值+分子分母+样本量 /
    未生效规则清单（原因）/ 定位宣言 + "建议仅供参考，不自动修改配置"
  · **数据不足降级**：样本不足一律"数据不足"，绝不出"建议移除"
  · **证据完整性硬门**：每条建议缺任一项 → 该条不输出（抛错）
  · **与真值对账**：`expected_suggestion` 逐 server 与报告建议标签一致（M5 直接消费真值）
  · 退出码语义：命中"建议移除" → 1，否则 0（README 明示）
  · 双跑逐字节一致（确定性）

变异验证（`tools/mutation_check.py`，M5 六项）：
  · 渲染出口摘掉外链断言 → 必红
  · `report/` 引入除法 → 口径唯一性守门必红
  · 样本门恒真（小样本也出建议）→ 必红
  · 证据完整性恒真 → 必红
  · 与真值 expected_suggestion 的对账比较恒真 → 必红
  · 未生效规则清单从报告中消失 → 必红
"""

import ast
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
REPORT_DIR = os.path.join(SRC_DIR, "opslens", "report")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from opslens import config  # noqa: E402
from opslens import pipeline  # noqa: E402
from opslens import report as report_module  # noqa: E402
from opslens.report import guard  # noqa: E402
from opslens.report import html as html_module  # noqa: E402
from opslens.report import markdown as markdown_module  # noqa: E402
from opslens.report import suggestions as suggestions_module  # noqa: E402


@pytest.fixture(scope="module")
def truth():
    with open(os.path.join(SYNTHETIC_DIR, "truth.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def built():
    """按 CLI 同一条通路装配报告载荷（scan → aggregate → attribute → report）。"""
    rules = config.load_rules()
    events, events_report = pipeline.scan_home(SYNTHETIC_DIR)
    agg_payload = pipeline.aggregate_events(events, rules)
    attr_payload = pipeline.attribute_events(events, rules)
    payload = pipeline.report_events(events_report, agg_payload, attr_payload, rules)
    return payload


@pytest.fixture(scope="module")
def rendered(built):
    return {
        "markdown": markdown_module.render_markdown(built),
        "html": html_module.render_html(built),
    }


def _report_py_files():
    """`report/` 包内全部 .py 文件（AST 守门的扫描面）。"""
    found = []
    for name in sorted(os.listdir(REPORT_DIR)):
        if name.endswith(".py"):
            found.append(os.path.join(REPORT_DIR, name))
    return found


# ---------------------------------------------------------------------------
# 渲染层零判定（AST 守门）
# ---------------------------------------------------------------------------


def test_report_package_scan_face_is_not_empty():
    """扫描面非空自证：防"目录写错 → 扫 0 个 → 永远绿"。"""
    files = _report_py_files()
    assert len(files) >= 4, "report/ 扫描面只有 {0} 个文件".format(len(files))


def test_report_package_has_no_division():
    """**渲染层零判定**：`report/` 内不得出现 `BinOp(Div)`（plan/02 §二、plan/03 §4.2）。

    一切数字与判定只来自 `report.json`；渲染器只做排版。报告层出现除法 =
    "第二份比率计算" = 数值口径不一致的直接来源。
    """
    offenders = []
    scanned = 0
    for path in _report_py_files():
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        scanned += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                offenders.append("{0}:{1}".format(os.path.basename(path), node.lineno))
    assert scanned >= 4
    assert offenders == [], "报告层出现除法（渲染层零判定被破坏）：{0}".format(offenders)


def test_division_detector_actually_detects():
    """探针自证：含除法的样例源码必须被本守门的检测逻辑命中（否则是假门）。"""
    tree = ast.parse("value = numerator / denominator\n")
    hit = any(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) for node in ast.walk(tree))
    assert hit


FORBIDDEN_REPORT_IMPORTS = ("opslens.aggregate", "opslens.attribute", "opslens.bench", "opslens.config")

# `report/` 下每个模块所属的包路径（相对 import 的解析基准）
_REPORT_PACKAGE = "opslens.report"


def _resolve_import(node, package):
    """把 import 节点解析成**候选绝对模块名**（相对 import 按所属包展开）。

    两种形态都必须覆盖，否则守门是假门：
      · `from .. import aggregate` —— `node.module` 是 None，违规名在 `node.names` 里，
        绝对名是 `opslens.aggregate`（level=2 从 `opslens.report` 上溯到 `opslens`）。
      · `from opslens import config` —— `node.module` 是 `opslens`，而实际被导入的模块是
        `opslens.config`（名字在 `node.names` 里）。**只看 module 会漏判这一形态**。
    故 `from X import Y` 一律同时产出 `X` 与 `X.Y` 两个候选（AST 无法区分"子模块"与"包内名字"）。
    """
    resolved = []
    if isinstance(node, ast.ImportFrom):
        parts = package.split(".") if node.level else []
        base_parts = parts[: len(parts) - (node.level - 1)] if node.level else []
        base = ".".join(base_parts + ([node.module] if node.module else []))
        if base:
            resolved.append(base)
        for alias in node.names:
            resolved.append((base + "." if base else "") + alias.name)
    elif isinstance(node, ast.Import):
        resolved.extend(alias.name for alias in node.names)
    return resolved


def _forbidden_imports_in(tree, package=_REPORT_PACKAGE):
    """返回树中指向引擎/规则层的 import（按所属包解析相对 import）。"""
    found = []
    for node in ast.walk(tree):
        for name in _resolve_import(node, package):
            if name in FORBIDDEN_REPORT_IMPORTS:
                found.append(name)
    return found


def test_report_package_does_not_import_engine_or_rules():
    """报告层**不读规则包、不 import 聚合/归因/基准层**（plan/02 §二依赖方向铁律）。"""
    offenders = []
    for path in _report_py_files():
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        for hit in _forbidden_imports_in(tree):
            offenders.append("{0}:{1}".format(os.path.basename(path), hit))
    assert offenders == [], "报告层 import 了引擎/规则层：{0}".format(offenders)


def test_forbidden_import_detector_actually_detects():
    """探针自证：相对/绝对两种违规 import 形态都必须被识别（否则本守门是假门）。"""
    assert _forbidden_imports_in(ast.parse("from .. import aggregate\n")) == ["opslens.aggregate"]
    assert _forbidden_imports_in(ast.parse("from ..aggregate import aggregate\n")) == ["opslens.aggregate"]
    assert _forbidden_imports_in(ast.parse("from opslens import config\n")) == ["opslens.config"]
    assert _forbidden_imports_in(ast.parse("import opslens.attribute\n")) == ["opslens.attribute"]
    # 反向自证：自家包内 import 与 stdlib 不得被误判（否则守门会被关掉）
    assert _forbidden_imports_in(ast.parse("from . import guard\n")) == []
    assert _forbidden_imports_in(ast.parse("from .. import serialize\n")) == []
    assert _forbidden_imports_in(ast.parse("import os\n")) == []


def test_report_source_has_no_threshold_literals():
    """零字面量：报告层不得出现阈值数值字面量（阈值一律参数注入，K9）。"""
    rules = config.load_rules()
    thresholds = rules.thresholds
    literals = [
        thresholds["remove_candidate"]["failure_rate_gte"],
        thresholds["remove_candidate"]["calls_total_gte"],
        thresholds["cost_heavy"]["turn_token_avg_gte"],
    ]
    offenders = []
    for path in _report_py_files():
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        for value in literals:
            if repr(value) in source or str(value) in source:
                offenders.append("{0} 含阈值字面量 {1}".format(os.path.basename(path), value))
    assert offenders == [], "报告层写死了阈值：{0}".format(offenders)


# ---------------------------------------------------------------------------
# 无外链硬断言（断网可开）
# ---------------------------------------------------------------------------


def test_render_outputs_contain_no_external_resources(rendered):
    """渲染产物零外链（HTML 内联 CSS，无 `<link>` / `<script src>` / `http(s)://`）。"""
    for name, text in rendered.items():
        assert guard.find_external_tokens(text) == [], "{0} 含外链构造".format(name)


def test_guard_is_load_bearing_at_the_render_exit():
    """**常驻断言**（不只测试里验一次）：渲染出口真的调用它——含外链的输入必须当场炸。

    直接调用渲染器并喂入一个"带外链"的载荷字段，证明断言在**出口**上生效，
    而不是只在测试里对已知产物做一次扫描。
    """
    rules = config.load_rules()
    events, events_report = pipeline.scan_home(SYNTHETIC_DIR)
    payload = pipeline.report_events(
        events_report,
        pipeline.aggregate_events(events, rules),
        pipeline.attribute_events(events, rules),
        rules,
    )
    poisoned = json.loads(json.dumps(payload))
    # 往一个必然被渲染的字段里注入外链（模拟"某次改动偷偷引入 CDN 字体"）
    poisoned["positioning"]["statement"] = 'see <link rel="stylesheet" href="https://cdn.example/x.css">'
    with pytest.raises(AssertionError):
        html_module.render_html(poisoned)
    with pytest.raises(AssertionError):
        markdown_module.render_markdown(poisoned)


def test_external_token_detector_actually_detects():
    """探针自证：各类外链构造都必须被检出（否则"零外链"是空转）。"""
    samples = [
        '<link rel="stylesheet" href="x.css">',
        '<script src="a.js"></script>',
        '<img src="x.png">',
        "http://example.com/x",
        "https://example.com/x",
        "background: url(foo.png)",
        "@import 'x.css';",
    ]
    for sample in samples:
        assert guard.find_external_tokens(sample), "探针漏判：{0}".format(sample)
    # 反向自证：内联样式表不得被误判（否则守门会被关掉）
    assert guard.find_external_tokens('<style>body { color: red; }</style>') == []


# ---------------------------------------------------------------------------
# 单一渲染源：两格式内容一致是**结构性质**
# ---------------------------------------------------------------------------


def test_md_and_html_render_from_the_same_payload(built, rendered):
    """MD/HTML 每个数字都来自同一份 `report.json`（同一 payload 渲染两遍）。"""
    for entry in built["suggestions"]:
        # 建议的样本量与分母必须两格式都出现（若某渲染器自己另算，就会对不上）
        needle = str(entry["sample_size"])
        assert needle in rendered["markdown"]
        assert needle in rendered["html"]
    # 关键数字两格式同源
    for key in ("calls_total", "calls_error", "calls_unknown"):
        assert str(built["summary"][key]) in rendered["markdown"]
        assert str(built["summary"][key]) in rendered["html"]


def test_render_is_deterministic_on_double_run(built):
    md_one = markdown_module.render_markdown(built)
    md_two = markdown_module.render_markdown(built)
    html_one = html_module.render_html(built)
    html_two = html_module.render_html(built)
    assert md_one == md_two and html_one == html_two


# ---------------------------------------------------------------------------
# 报告必含章节（plan/03 §4.2）
# ---------------------------------------------------------------------------


def test_report_has_all_required_sections(built, rendered):
    required = (
        "source_declaration",
        "unknown_partition",
        "failure_attribution",
        "suggestions",
        "insufficient_data",
        "positioning",
    )
    for key in required:
        assert key in built, "报告载荷缺章节 {0}".format(key)
    for name, text in rendered.items():
        assert "数据来源与覆盖声明" in text, name
        assert "独立分区" in text, name
        assert "建议清单" in text, name
        assert "未生效规则" in text, name
        assert "不自动修改配置" in text, name


def test_unknown_partition_is_visible_and_not_folded_into_stats(built):
    """`unknown` 必须**独立分区**且可见：未声明态不得看起来像"没问题"。"""
    partition = built["unknown_partition"]
    assert partition["calls_unknown"] == built["summary"]["calls_unknown"]
    assert partition["calls_unknown"] > 0, "合成数据必须含 unknown 样本，否则本节没演练到"
    # unknown 独立于成功：分区里 ok/error/unknown 三列都单列
    row = [item for item in partition["by_server"] if item["calls_unknown"]][0]
    assert row["calls_ok"] + row["calls_error"] + row["calls_unknown"] == row["calls_total"]


def test_unknown_is_not_in_failure_rate_denominator(built):
    """K1 在报告层仍成立：建议的分母 = ok + error，不含 unknown。"""
    for entry in built["suggestions"]:
        if entry["axis"] != "failure_rate":
            continue
        row = [item for item in built["server_metrics"] if item["server"] == entry["server"]][0]
        assert entry["denominator"] == row["calls_ok"] + row["calls_error"]
        assert entry["denominator"] != row["calls_total"] or row["calls_unknown"] == 0


def test_ineffective_rules_are_listed_with_reasons(built, rendered):
    """未生效规则清单 + 原因（plan/03 §3.2 硬门）。"""
    ineffective = built["failure_attribution"]["ineffective_rules"]
    assert ineffective, "规则包存在未生效规则，报告必须列出"
    for item in ineffective:
        assert item["id"] and item["reasons"]
    for name, text in rendered.items():
        assert "F-REFUSE-1" in text, name
        assert "pending" in text or "verified_samples" in text, name


def test_positioning_declaration_is_present(built, rendered):
    """定位宣言 + "建议仅供参考，不自动修改配置"声明。"""
    positioning = built["positioning"]
    assert "只读" in positioning["statement"]
    assert "不自动修改配置" in positioning["not_auto_modify"]
    assert "仅供参考" in positioning["not_auto_modify"]
    for name, text in rendered.items():
        assert "不自动修改配置" in text, name


# ---------------------------------------------------------------------------
# 建议证据完整性（plan/03 §4.1 硬门）
# ---------------------------------------------------------------------------


def test_every_suggestion_carries_full_evidence(built):
    """每条建议必须附：口径 + 阈值取值 + 分子/分母 + 样本量（缺任一项即不输出）。"""
    assert built["suggestions"], "合成数据应至少触发一条建议（否则本断言空转）"
    for entry in built["suggestions"]:
        for key in ("metric", "value", "numerator", "denominator", "sample_size", "threshold", "sample_requirement", "basis"):
            assert entry.get(key) is not None, "{0}/{1} 缺证据项 {2}".format(entry["type"], entry["server"], key)
        assert entry["threshold"], "阈值取值必须非空"
        assert entry["sample_requirement"], "样本门槛必须非空"
        assert entry["numerator"] is not None and entry["denominator"] is not None


def test_evidence_gate_rejects_incomplete_entries():
    """证据完整性硬门可证伪：缺任一项 → `assert_evidence_complete` 必须抛错。"""
    complete = {
        "type": suggestions_module.SUGGESTION_REMOVE,
        "axis": suggestions_module.AXIS_FAILURE_RATE,
        "metric": "failure_rate",
        "source": "claude_code",
        "server": "fake",
        "value": 0.6,
        "numerator": 24,
        "denominator": 40,
        "sample_size": 40,
        "sample_requirement": {"calls_total_gte": 20},
        "threshold": {"failure_rate_gte": 0.5},
        "basis": "口径……",
    }
    assert suggestions_module.assert_evidence_complete(dict(complete)) is not None
    # 阳性对照：缺一项必须抛错
    broken = dict(complete)
    broken["sample_size"] = None
    with pytest.raises(AssertionError):
        suggestions_module.assert_evidence_complete(broken)


def test_sample_gate_degrades_to_insufficient_data():
    """样本不足一律降级"数据不足"，**绝不出建议**（plan/03 §4.1）。"""
    thresholds = config.load_rules().thresholds
    row = {
        "source": "claude_code",
        "server": "tiny",
        "calls_total": 3,
        "calls_ok": 1,
        "calls_error": 2,
        "calls_unknown": 0,
        "failure_rate": 0.666667,
        "failure_rate_numerator": 2,
        "failure_rate_denominator": 3,
        "token_samples": 3,
        "token_missing": 0,
        "tokens_input": 1,
        "tokens_output": 1,
        "tokens_cache_read": 0,
        "tokens_cache_creation": 0,
        "turn_token_avg": 999999.0,
    }
    outcome = suggestions_module.evaluate_server(row, thresholds)
    assert outcome["suggestions"] == [], "样本不足却给出了建议（小样本下建议移除 = 硬违规）"
    assert outcome["failure_suggestion"] == suggestions_module.SUGGESTION_LOW_SIGNAL
    assert any(item["axis"] == suggestions_module.AXIS_FAILURE_RATE for item in outcome["insufficient"])


def test_sample_gate_is_load_bearing():
    """样本门是**真门**：把同一行样本量抬到门槛之上，必须立刻变成"建议移除"。"""
    thresholds = config.load_rules().thresholds
    min_calls = thresholds["min_samples"]["calls_total_gte"]
    base = {
        "source": "claude_code",
        "server": "boundary",
        "calls_total": min_calls,
        "calls_ok": 0,
        "calls_error": min_calls,
        "calls_unknown": 0,
        "failure_rate": 1.0,
        "failure_rate_numerator": min_calls,
        "failure_rate_denominator": min_calls,
        "token_samples": 0,
        "token_missing": min_calls,
        "tokens_input": None,
        "tokens_output": None,
        "tokens_cache_read": None,
        "tokens_cache_creation": None,
        "turn_token_avg": None,
    }
    outcome = suggestions_module.evaluate_server(base, thresholds)
    assert [entry["type"] for entry in outcome["suggestions"]] == [suggestions_module.SUGGESTION_REMOVE]
    # 阳性对照：样本量减一 → 立刻降级
    below = dict(base, calls_total=min_calls - 1, failure_rate_denominator=min_calls - 1)
    assert suggestions_module.evaluate_server(below, thresholds)["suggestions"] == []


# ---------------------------------------------------------------------------
# 与植入真值对账（M5 直接消费 `expected_suggestion`）
# ---------------------------------------------------------------------------


def test_failure_suggestion_matches_truth_per_server(built, truth):
    """逐 server 的失败轴建议标签必须与真值 `expected_suggestion` 一致。

    真值的期望值由 `tools/gen_synthetic_logs.py::expected_suggestion` 独立推导
    （与报告层实现相互独立），故这是**真对账**而非"引擎自证"。
    """
    by_metric = dict(((row["source"], row["server"]), row) for row in built["server_metrics"])
    checked = 0
    for server in truth["claude"]["servers"]:
        row = by_metric[("claude_code", server["server"])]
        outcome = suggestions_module.evaluate_server(row, config.load_rules().thresholds)
        assert outcome["failure_suggestion"] == server["expected_suggestion"], server["server"]
        checked += 1
    assert checked == len(truth["claude"]["servers"])
    # Codex 侧同样对账（真值声明 low_signal）
    codex = by_metric[("codex", "<codex>")]
    outcome = suggestions_module.evaluate_server(codex, config.load_rules().thresholds)
    assert outcome["failure_suggestion"] == truth["codex"]["expected_suggestion"]


def test_truth_reconciliation_would_differ_if_engine_were_wrong(built, truth):
    """可证伪自证：真值里确实存在**不同**的期望标签，否则上面那条是空转。"""
    labels = set(server["expected_suggestion"] for server in truth["claude"]["servers"])
    assert len(labels) >= 3, "真值期望标签过于单一，对账可能空转：{0}".format(labels)
    assert "remove_candidate" in labels and "investigate" in labels


def test_remove_candidate_count_matches_truth(built, truth):
    """"建议移除"清单必须与真值声明的 server 集合逐项一致。"""
    expected = sorted(
        server["server"] for server in truth["claude"]["servers"] if server["expected_suggestion"] == "remove_candidate"
    )
    got = sorted(entry["server"] for entry in built["suggestions"] if entry["type"] == "remove_candidate")
    assert got == expected


# ---------------------------------------------------------------------------
# 退出码语义（README 明示）
# ---------------------------------------------------------------------------


def test_exit_code_is_findings_when_remove_candidate_hits(built):
    """命中"建议移除" → 退出码 1（检出问题，不是跑挂）。"""
    from opslens import exit_codes

    assert built["summary"]["remove_candidate"] >= 1
    assert report_module.exit_code_for(built) == exit_codes.EXIT_FINDINGS


def test_exit_code_is_ok_when_no_remove_candidate():
    """阳性对照：无"建议移除" → 退出码 0。"""
    from opslens import exit_codes

    payload = {"summary": {"remove_candidate": 0}}
    assert report_module.exit_code_for(payload) == exit_codes.EXIT_OK


# ---------------------------------------------------------------------------
# 入仓示例报告（examples/）：**冻结产物 + 重生成结果两层都断言**
# ---------------------------------------------------------------------------

EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")


def test_committed_examples_exist():
    """示例报告必须入仓（提交材料第 5 项：HTML/Markdown 各一份，基于合成数据）。"""
    for name in ("report.md", "report.html", "report.json"):
        assert os.path.isfile(os.path.join(EXAMPLES_DIR, name)), "缺示例产物 {0}".format(name)


def test_committed_examples_are_byte_identical_to_regeneration(tmp_out):
    """冻结产物 == 由合成数据重生成的结果（防"手改示例报告"与"生成器变异"两类漂移）。

    HANDOFF §四 item 9 的正解：**冻结产物 + 重生成结果两层都断言**——
    只查冻结产物会漏掉生成器变异；只查重生成会漏掉"示例报告被手改"。

    复现口径与 CI 一致：以**仓库相对路径** `data/synthetic` 扫描（故示例报告里的
    `home` 是可移植的相对路径，不含本机绝对路径），再比对三份产物逐字节。
    """
    rules = config.load_rules()
    relative_home = os.path.relpath(SYNTHETIC_DIR, REPO_ROOT).replace("\\", "/")
    cwd = os.getcwd()
    try:
        os.chdir(REPO_ROOT)
        events, events_report = pipeline.scan_home(relative_home)
        payload = pipeline.report_events(
            events_report,
            pipeline.aggregate_events(events, rules),
            pipeline.attribute_events(events, rules),
            rules,
        )
        regenerated = report_module.render(payload, tmp_out)
        pairs = (
            ("report.md", regenerated["markdown"]),
            ("report.html", regenerated["html"]),
            ("report.json", regenerated["json"]),
        )
        for name, fresh_path in pairs:
            with open(fresh_path, "r", encoding="utf-8") as handle:
                fresh = handle.read()
            with open(os.path.join(EXAMPLES_DIR, name), "r", encoding="utf-8") as handle:
                frozen = handle.read()
            assert frozen == fresh, "examples/{0} 与重生成结果不一致（示例报告漂移）".format(name)
    finally:
        os.chdir(cwd)


def test_committed_examples_contain_no_external_resources():
    """入仓的 HTML/MD 示例断网可开（零外链）——产物级复核，不只查渲染出口。"""
    for name in ("report.md", "report.html"):
        with open(os.path.join(EXAMPLES_DIR, name), "r", encoding="utf-8") as handle:
            text = handle.read()
        assert guard.find_external_tokens(text) == [], "examples/{0} 含外链".format(name)


def test_committed_examples_are_based_on_synthetic_data():
    """示例报告必须基于合成数据（真实会话日志不入仓）：来源声明里只有 fake-* server。"""
    with open(os.path.join(EXAMPLES_DIR, "report.json"), "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    servers = [row["server"] for row in payload["server_metrics"]]
    assert servers, "示例报告无 server 维度"
    for server in servers:
        assert server == "<codex>" or server.startswith("fake-"), "示例报告含非合成 server：{0}".format(server)
