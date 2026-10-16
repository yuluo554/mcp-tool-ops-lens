"""模块 5 · 真值基准（引擎输出 vs 植入真值对账，plan/03 §5、plan/04 §三）。

职责：拿**冻结的合成数据**（`data/synthetic/`）跑一遍引擎（模块 1→2→3），
把引擎输出与 `truth.json` 的**植入期望**逐维度对账，差异**逐条列出**。
本模块**不生成**数据、**不写盘**、**不读时钟**——它只读、只算、只比对。

K12 纪律（真值库只存输入与期望）：本模块的一切"观测"都在**运行时实算**
（重新扫描 + 重新聚合 + 重新归因），**绝不读 `truth.json` 里的任何观测字段**
（该库已被 `tests/test_synthetic_data.py::test_truth_has_no_observed_fields` 禁止出现 `observed_*`）。
真值只提供"期望值"，引擎只提供"实算值"，两者在 `_check_*` 里相遇。

## 分层（plan/03 §5.3「分套件对账」）

| 层 | 套件前缀 | 对账什么 |
|---|---|---|
| 样本驱动层 `sample` | `S-*` | 合成日志直接对账：三态计数 / 失败率 / 重试 / token / 耗时 / 两级维度 |
| 规则驱动层 `rule` | `R-*` | 规则包生效门控 + 失败分类分布（未生效规则落 `other` 的期望） |
| 覆盖声明层 `coverage` | `C-*` | 消费 `manifest.json`：总数/采样数双登记 + "抽样覆盖非穷举"声明 |
| 双基线层 `baseline` | `B-*` | 解析对账基线（精确对账 + 计数级 F1）+ e2e 双跑逐字节一致 |

## 可证伪探活（DoD 硬项）

**每套件**都配一个 `probe`：它把输入**故意弄坏**（如把 `is_error=True` 判成 `ok`、
把未生效规则塞进计算路径），然后**用同一套 check 去跑被弄坏的输入**——
必须报出 ≥1 条差异。探活**未变红** = 该套件是假门，基准自己判自己失败（`exit 1`）。
这让"基准全绿"这件事本身可证伪：它不只跑一次，还证明"弄坏了会红"。

## 退出码三语义（plan/02 §六，锁进测试）

- `0` 达标：全部选中套件通过，且全部探活变红。
- `1` 未达标：任一套件报出差异，**或**任一套件 `not_enabled`（"未启用"不得冒充通过），
  **或**任一探活未变红（假门）。
- `2` 用法与未知名：`--only <未知套件名>`。

## 口径唯一性（K15）

本模块计算**解析质量指标**（precision / recall / F1）——那是"一致性比率"，
不是域口径（`failure_rate` / `turn_token_avg`）的第二份计算。
故 `BinOp(Div)` 在本模块出现属白名单扩充（理由见 `tests/test_aggregate.py::DIV_ALLOWED_FILES`），
域口径仍然只在 `aggregate.py` / `attribute.py` / 生成器三处。
"""

import hashlib
import os

from . import attribute as attribute_module
from . import config
from . import exit_codes
from . import pipeline
from . import schema
from . import serialize

# 基准载荷的 schema 标识（唯一出处）
BENCH_SCHEMA = "opslens.bench/1"

# 层标识（--check 用 `LAYER_BASELINE` 选中"双基线"）
LAYER_SAMPLE = "sample"
LAYER_RULE = "rule"
LAYER_COVERAGE = "coverage"
LAYER_BASELINE = "baseline"

# 套件状态（三态：通过 / 未达标 / 未启用）
STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_NOT_ENABLED = "not_enabled"

# 合成数据目录的环境变量覆盖点（测试可指向临时目录）
SYNTHETIC_DIR_ENV = "OPSLENS_SYNTHETIC_DIR"

TRUTH_FILE = "truth.json"
MANIFEST_FILE = "manifest.json"


# ---------------------------------------------------------------------------
# 数据定位与输入装载
# ---------------------------------------------------------------------------


def default_synthetic_dir():
    """仓库内 `data/synthetic` 的定位（与 `config.default_rules_dir` 同源手法）。

    包外三级：`src/opslens/bench.py` → 仓库根/data/synthetic。
    允许 `OPSLENS_SYNTHETIC_DIR` 覆盖，便于测试指向临时目录。
    """
    override = os.environ.get(SYNTHETIC_DIR_ENV)
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(repo_root, "data", "synthetic")


def _read_required_json(path, what):
    if not os.path.isfile(path):
        raise exit_codes.DataUnavailableError("缺少{0}：{1}".format(what, path))
    try:
        payload = serialize.read_json(path)
    except ValueError as exc:
        raise exit_codes.DataUnavailableError("{0} 不是合法 JSON：{1}（{2}）".format(what, path, exc))
    return payload


def build_bundle(data_dir=None, home=None, rules_dir=None):
    """装载对账输入：真值 + 覆盖度 manifest + 规则包 + **运行时实算的引擎输出**。

    "观测"一律在此刻实算（K12）：`events` / `agg` / `attr` 都来自真实引擎调用，
    与 `truth.json` 无任何数据通路——真值只提供期望值。
    """
    data = data_dir or default_synthetic_dir()
    if not os.path.isdir(data):
        raise exit_codes.DataUnavailableError("合成数据目录不存在：{0}".format(data))

    truth = _read_required_json(os.path.join(data, TRUTH_FILE), "植入真值")
    manifest = _read_required_json(os.path.join(data, MANIFEST_FILE), "覆盖度 manifest")
    if not isinstance(truth, dict) or not isinstance(manifest, dict):
        raise exit_codes.DataUnavailableError("真值 / manifest 顶层必须是对象：{0}".format(data))

    rules = config.load_rules(rules_dir)  # ConfigError 由 CLI 映射为 exit 4
    scan_home = home or data
    max_error_chars = (rules.params.get("error_text") or {}).get("max_chars")
    events, report = pipeline.scan_home(scan_home, max_error_chars)
    if not events:
        raise exit_codes.DataUnavailableError("扫描面为空，基准无可对账样本：{0}".format(scan_home))

    return {
        "data_dir": data,
        "home": scan_home,
        "truth": truth,
        "manifest": manifest,
        "rules": rules,
        "events": events,
        "agg": pipeline.aggregate_events(events, rules),
        "attr": pipeline.attribute_events(events, rules),
    }


# ---------------------------------------------------------------------------
# 索引与差异条目
# ---------------------------------------------------------------------------


def _diff(dimension, key, expected, actual, note=""):
    return {"dimension": dimension, "key": key, "expected": expected, "actual": actual, "note": note}


def _agg_by_server(bundle):
    return dict(((row["source"], row["server"]), row) for row in bundle["agg"]["server_level"])


def _attr_by_server(bundle):
    return dict(((row["source"], row["server"]), row) for row in bundle["attr"]["by_server"])


def _truth_servers(bundle):
    """真值声明的全部 server 维度：Claude 侧逐 server + Codex 侧单条。"""
    pairs = [(schema.SOURCE_CLAUDE_CODE, item) for item in bundle["truth"]["claude"]["servers"]]
    pairs.append((schema.SOURCE_CODEX, bundle["truth"]["codex"]))
    return pairs


def _label(source, server):
    return "{0}/{1}".format(source, server)


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ok(diffs=None, metrics=None):
    return {"diffs": diffs or [], "metrics": metrics or {}}


# ---------------------------------------------------------------------------
# 样本驱动层（S-*）：直接对合成日志的三态 / 失败率 / 重试 / token / 耗时 / 两级对账
# ---------------------------------------------------------------------------


def _check_three_state(bundle):
    """逐 server 三态计数与真值**逐项相等**（K1 的直接对账）。"""
    diffs = []
    by_server = _agg_by_server(bundle)
    checked = 0
    for source, declared in _truth_servers(bundle):
        key = (source, declared["server"])
        row = by_server.get(key)
        if row is None:
            diffs.append(_diff("three_state", _label(source, declared["server"]), "引擎输出存在该 server", None))
            continue
        checked += 1
        for field in ("calls_total", "calls_ok", "calls_error", "calls_unknown"):
            if row[field] != declared[field]:
                diffs.append(
                    _diff(
                        "three_state." + field,
                        declared["server"],
                        declared[field],
                        row[field],
                        "引擎三态计数与植入真值不符",
                    )
                )
    return _ok(diffs, {"servers_checked": checked})


def _check_failure_rate(bundle):
    """逐 server `failure_rate` + 分子分母与真值相等；分母**不含 unknown**（K1）。"""
    diffs = []
    by_server = _agg_by_server(bundle)
    for source, declared in _truth_servers(bundle):
        row = by_server.get((source, declared["server"]))
        if row is None:
            diffs.append(_diff("failure_rate", declared["server"], "存在", None))
            continue
        if row["failure_rate"] != declared["expected_failure_rate"]:
            diffs.append(
                _diff("failure_rate", declared["server"], declared["expected_failure_rate"], row["failure_rate"])
            )
        if row["failure_rate_numerator"] != declared["calls_error"]:
            diffs.append(
                _diff("failure_rate.numerator", declared["server"], declared["calls_error"], row["failure_rate_numerator"])
            )
        # 分母口径对账：真值声明的 ok+error 即期望分母；若含 unknown 会与之不等
        expected_denominator = declared["calls_ok"] + declared["calls_error"]
        if row["failure_rate_denominator"] != expected_denominator:
            diffs.append(
                _diff(
                    "failure_rate.denominator",
                    declared["server"],
                    expected_denominator,
                    row["failure_rate_denominator"],
                    "分母必须 = ok + error（unknown 不进分母）",
                )
            )
    return _ok(diffs)


def _check_retry_count(bundle):
    """逐 server `retry_count` 与真值相等（期望值必须可由日志按窗口规则复算）。

    真值只在"建模了重试"的 server 上声明 `expected_retry_count`（Codex 侧未建模，
    不声明即不比对）；未声明的 server 计入 `undeclared`，**不静默当作通过**。
    """
    diffs = []
    by_server = _agg_by_server(bundle)
    checked = 0
    undeclared = 0
    for source, declared in _truth_servers(bundle):
        if "expected_retry_count" not in declared:
            undeclared += 1
            continue
        row = by_server.get((source, declared["server"]))
        if row is None:
            diffs.append(_diff("retry_count", declared["server"], "存在", None))
            continue
        checked += 1
        if row["retry_count"] != declared["expected_retry_count"]:
            diffs.append(
                _diff("retry_count", declared["server"], declared["expected_retry_count"], row["retry_count"])
            )
    return _ok(diffs, {"servers_checked": checked, "undeclared": undeclared})


def _check_token(bundle):
    """token 四项分列 + 样本量口径：Claude 侧按轮次可得，Codex 侧**不摊到调用**（K2/K3）。"""
    diffs = []
    by_server = _agg_by_server(bundle)
    token_attribution = bundle["truth"]["codex"].get("token_attribution")
    for row in bundle["agg"]["server_level"]:
        label = _label(row["source"], row["server"])
        for key in ("tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation"):
            if key not in row:
                diffs.append(_diff("token.columns", label, key, None, "token 四项必须分列（不合并）"))
        if "tokens_total" in row:
            diffs.append(_diff("token.columns", label, "无合并列", "tokens_total", "合并列会重复计数缓存"))
        if row["token_samples"] + row["token_missing"] != row["calls_total"]:
            diffs.append(
                _diff("token.samples", label, row["calls_total"], row["token_samples"] + row["token_missing"])
            )
        if row["source"] == schema.SOURCE_CODEX:
            # 真值声明 Codex token 只在会话级 → 引擎必须**一条都不摊到调用**
            if row["token_samples"] != 0:
                diffs.append(
                    _diff(
                        "token.codex_attribution",
                        label,
                        "token_samples=0（真值声明 {0}）".format(token_attribution),
                        row["token_samples"],
                        "会话级 token 被摊到单次调用 = 造假结论（K3）",
                    )
                )
            if row["turn_token_avg"] is not None:
                diffs.append(_diff("token.codex_avg", label, None, row["turn_token_avg"]))
        else:
            # 本机实测：携带 tool_use 的 assistant 消息 100% 带 usage（data/README §五B）
            if row["token_samples"] != row["calls_total"]:
                diffs.append(
                    _diff("token.samples", label, row["calls_total"], row["token_samples"], "Claude 侧轮次 token 应全覆盖")
                )
    return _ok(diffs)


def _check_duration(bundle):
    """耗时口径：Claude 侧**不可得**（不得用 `lastToolDuration` 冒充），Codex 侧可得；两侧不混算（K4）。"""
    diffs = []
    for row in bundle["agg"]["server_level"]:
        label = _label(row["source"], row["server"])
        if row["source"] == schema.SOURCE_CLAUDE_CODE:
            if row["duration_available"] is not False:
                diffs.append(_diff("duration.available", label, False, row["duration_available"], "Claude 侧耗时不可得"))
            if row["duration_samples"] != 0:
                diffs.append(_diff("duration.samples", label, 0, row["duration_samples"]))
            if row["duration_avg_ms"] is not None:
                diffs.append(_diff("duration.avg", label, None, row["duration_avg_ms"], "不可得的耗时不得出均值"))
        elif row["source"] == schema.SOURCE_CODEX:
            if row["duration_available"] is not True:
                diffs.append(
                    _diff("duration.available", label, True, row["duration_available"], "Codex 侧 Wall time 可得")
                )
            if row["duration_samples"] < 1:
                diffs.append(_diff("duration.samples", label, "≥1", row["duration_samples"]))
    return _ok(diffs)


def _check_two_level(bundle):
    """两级维度：tool 级合计 == server 级 == 汇总；两级都输出 `unknown`（"未声明"不得像"没问题"）。"""
    diffs = []
    agg = bundle["agg"]
    server_level = agg["server_level"]
    tool_level = agg["tool_level"]
    if not server_level or not tool_level:
        return _ok([_diff("two_level", "scan_face", "两级都非空", "server={0} tool={1}".format(len(server_level), len(tool_level)))])

    for level, rows in (("server", server_level), ("tool", tool_level)):
        for row in rows:
            if row["calls_ok"] + row["calls_error"] + row["calls_unknown"] != row["calls_total"]:
                diffs.append(_diff("two_level.identity", "{0}/{1}".format(level, row["server"]), row["calls_total"], row["calls_ok"] + row["calls_error"] + row["calls_unknown"]))

    # tool 级 → server 级 rollup（按 (source, server) 合计）
    rollup = {}
    for row in tool_level:
        bucket = rollup.setdefault((row["source"], row["server"]), {"calls_total": 0, "calls_ok": 0, "calls_error": 0, "calls_unknown": 0})
        for field in bucket:
            bucket[field] += row[field]
    for row in server_level:
        key = (row["source"], row["server"])
        got = rollup.get(key)
        if got is None:
            diffs.append(_diff("two_level.rollup", _label(*key), "tool 级存在对应行", None))
            continue
        for field in ("calls_total", "calls_ok", "calls_error", "calls_unknown"):
            if got[field] != row[field]:
                diffs.append(_diff("two_level.rollup." + field, row["server"], row[field], got[field], "tool 级合计与 server 级不符"))

    # 汇总与 server 级同口径
    totals = agg["totals"]
    for field in ("calls_total", "calls_ok", "calls_error", "calls_unknown"):
        expected = sum(row[field] for row in server_level)
        if totals[field] != expected:
            diffs.append(_diff("two_level.totals." + field, "totals", expected, totals[field]))

    # 两级都必须暴露 unknown 计数（真值里确有 unknown 样本，故不得为 0 全灭）
    if not any(row["calls_unknown"] for row in server_level):
        diffs.append(_diff("two_level.unknown", "server_level", "≥1 个 server 带 unknown", 0, "未声明态未在 server 级可见"))
    if not any(row["calls_unknown"] for row in tool_level):
        diffs.append(_diff("two_level.unknown", "tool_level", "≥1 个 tool 带 unknown", 0, "未声明态未在 tool 级可见"))
    return _ok(diffs)


# ---------------------------------------------------------------------------
# 规则驱动层（R-*）：生效门控 + 失败分类分布
# ---------------------------------------------------------------------------


def _expected_distribution(declared):
    """真值 → 期望分布（未生效规则覆盖的类别落 `other`）。"""
    expected = {}
    for mode, info in declared["failure_modes"].items():
        target = mode if info["rule_effective"] else attribute_module.CATEGORY_OTHER
        expected[target] = expected.get(target, 0) + info["calls"]
    return expected


def _check_category_distribution(bundle):
    """逐 server 失败分类分布与真值相等；未生效规则覆盖的类别必须落 `other`。"""
    diffs = []
    by_attr = _attr_by_server(bundle)
    by_agg = _agg_by_server(bundle)
    for source, declared in _truth_servers(bundle):
        key = (source, declared["server"])
        item = by_attr.get(key)
        if item is None:
            diffs.append(_diff("category.distribution", declared["server"], "存在归因行", None))
            continue
        got = dict((category, calls) for category, calls in item["categories"].items() if calls)
        expected = _expected_distribution(declared)
        if got != expected:
            diffs.append(_diff("category.distribution", declared["server"], expected, got, "归因分布与植入真值不符"))
        agg_row = by_agg.get(key)
        if agg_row is not None and item["calls_error"] != agg_row["calls_error"]:
            diffs.append(
                _diff("category.error_total", declared["server"], agg_row["calls_error"], item["calls_error"], "归因只消费 status=error")
            )
    return _ok(diffs)


def _check_rule_gate(bundle):
    """生效规则集 == 规则包门控结果；未生效规则逐条列出原因；真值声明的 rule_effective 与引擎一致（K10）。"""
    diffs = []
    rules = bundle["rules"]
    attr = bundle["attr"]
    expected_effective = [rule.get("id") for rule in rules.effective_patterns()]
    if attr["effective_rule_ids"] != expected_effective:
        diffs.append(_diff("rule.gate.effective", "effective_rule_ids", expected_effective, attr["effective_rule_ids"]))

    expected_ineffective = sorted(item["id"] for item in rules.ineffective_patterns())
    got_ineffective = sorted(item["id"] for item in attr["ineffective_rules"])
    if got_ineffective != expected_ineffective:
        diffs.append(_diff("rule.gate.ineffective", "ineffective_rules", expected_ineffective, got_ineffective))
    for item in attr["ineffective_rules"]:
        if not item.get("reasons"):
            diffs.append(_diff("rule.gate.reasons", item.get("id"), "原因非空", item.get("reasons")))

    # 真值侧对账：每个失败模式声明的 rule_effective 必须与"该规则是否在生效集里"一致
    for _source, declared in _truth_servers(bundle):
        for mode, info in declared["failure_modes"].items():
            rule_id = info.get("rule_id")
            if rule_id is None:
                continue
            actual_effective = rule_id in attr["effective_rule_ids"]
            if actual_effective != info["rule_effective"]:
                diffs.append(
                    _diff(
                        "rule.gate.truth",
                        "{0}/{1}".format(declared["server"], mode),
                        info["rule_effective"],
                        actual_effective,
                        "真值声明的规则生效性与引擎不符（{0}）".format(rule_id),
                    )
                )
    return _ok(diffs)


def _check_match_audit(bundle):
    """命中的规则/模式必须可审计：`rule_id` 必须来自生效规则，`pattern` 必须属于该规则。"""
    diffs = []
    attr = bundle["attr"]
    rules_by_id = dict((rule.get("id"), rule) for rule in bundle["rules"].patterns.get("rules", []))
    effective_ids = attr["effective_rule_ids"]
    for item in attr["matched_patterns"]:
        if item["rule_id"] not in effective_ids:
            diffs.append(
                _diff("match.audit.rule", item["rule_id"], "属于生效规则集", "未生效规则被用于匹配", "未生效规则不得进计算路径")
            )
            continue
        patterns = rules_by_id[item["rule_id"]].get("patterns") or []
        if item["pattern"] not in patterns:
            diffs.append(_diff("match.audit.pattern", item["rule_id"], "模式属于该规则", item["pattern"]))
    matched = attr["totals"]["matched"]
    other = attr["totals"][attribute_module.CATEGORY_OTHER]
    if matched + other != attr["totals"]["calls_error"]:
        diffs.append(_diff("match.audit.totals", "matched+other", attr["totals"]["calls_error"], matched + other))
    return _ok(diffs)


# ---------------------------------------------------------------------------
# 覆盖声明层（C-*）：消费 manifest 的"总数/采样数"双登记
# ---------------------------------------------------------------------------


def _check_manifest_coverage(bundle):
    """消费 `manifest.json`：逐维度"总数/采样数"双登记 + 显式"抽样覆盖非穷举" + 引擎总数与声明一致。"""
    diffs = []
    manifest = bundle["manifest"]
    declaration = manifest.get("declaration") or ""
    if "非穷举" not in declaration:
        diffs.append(_diff("coverage.declaration", "declaration", "显式声明抽样覆盖非穷举", declaration))
    coverage = manifest.get("coverage") or []
    if not coverage:
        return _ok([_diff("coverage.dimensions", "coverage", "至少一个覆盖维度", 0)])
    for item in coverage:
        name = item.get("dimension")
        if item.get("required_forms", 0) < 1:
            diffs.append(_diff("coverage.required", name, "≥1", item.get("required_forms")))
        if item.get("sampled_forms", 0) < item.get("required_forms", 0):
            diffs.append(_diff("coverage.sampled", name, item.get("required_forms"), item.get("sampled_forms"), "采样数低于要求（总数/采样数双登记未达标）"))
        if not item.get("items"):
            diffs.append(_diff("coverage.items", name, "逐项登记", None))
    # 引擎消费声明：汇总数与 manifest 声明的总数逐项相等
    totals = bundle["agg"]["totals"]
    declared_totals = manifest.get("totals") or {}
    if totals["calls_total"] != declared_totals.get("calls_total"):
        diffs.append(_diff("coverage.totals", "calls_total", declared_totals.get("calls_total"), totals["calls_total"]))
    three_state = None
    for item in coverage:
        if item.get("dimension") == "three_state":
            three_state = dict((entry["form"], entry.get("sampled_calls")) for entry in item["items"])
    if three_state is not None:
        for form in ("ok", "error", "unknown"):
            if totals["calls_" + form] != three_state.get(form):
                diffs.append(_diff("coverage.three_state", form, three_state.get(form), totals["calls_" + form]))
    # 规则包生效性登记与引擎一致
    rules_pack = manifest.get("rules_pack") or {}
    if rules_pack.get("total_rules") != len(bundle["rules"].patterns.get("rules", [])):
        diffs.append(_diff("coverage.rules.total", "total_rules", rules_pack.get("total_rules"), len(bundle["rules"].patterns.get("rules", []))))
    if rules_pack.get("effective_rules") != len(bundle["rules"].effective_patterns()):
        diffs.append(_diff("coverage.rules.effective", "effective_rules", rules_pack.get("effective_rules"), len(bundle["rules"].effective_patterns())))
    return _ok(diffs, {"dimensions": len(coverage)})


# ---------------------------------------------------------------------------
# 双基线层（B-*）：解析对账基线（计数级 F1）+ e2e 双跑逐字节一致
# ---------------------------------------------------------------------------


def _confusion_counts(bundle):
    """计数级混淆矩阵（正类 = `error`）。

    真值是**程序化精确植入**的、聚合粒度（不是逐条标注），故解析基线按
    "逐 server 错误计数" 建立混淆矩阵：对每个 server，引擎错误数与真值错误数取 min 记 tp，
    超出部分记 fp，缺口记 fn。计数完全相等时 tp = 总错误数、fp = fn = 0 → F1 = 1。
    """
    by_server = _agg_by_server(bundle)
    tp = fp = fn = 0
    for source, declared in _truth_servers(bundle):
        row = by_server.get((source, declared["server"]))
        engine_errors = row["calls_error"] if row is not None else 0
        expected_errors = declared["calls_error"]
        tp += min(engine_errors, expected_errors)
        fp += max(0, engine_errors - expected_errors)
        fn += max(0, expected_errors - engine_errors)
    return tp, fp, fn


def _ratio(numerator, denominator):
    """比率（**本模块唯一的除法落点**，见模块 docstring 的口径唯一性说明）。分母为 0 → None。"""
    if not denominator:
        return None
    return numerator / float(denominator)


def _check_parse_baseline(bundle):
    """解析对账基线（"双基线"之一）：三态逐 server 精确一致 + 计数级 precision/recall/F1 = 1。"""
    diffs = []
    tp, fp, fn = _confusion_counts(bundle)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    metrics = {
        "confusion": {"tp": tp, "fp": fp, "fn": fn},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "definition": "计数级混淆矩阵（正类=error，聚合粒度）；真值为精确植入，故 F1=1 等价于逐 server 错误计数完全一致",
    }
    if f1 != 1.0:
        diffs.append(_diff("baseline.parse.f1", "F1", 1.0, f1, "解析对账未达精确一致（tp={0} fp={1} fn={2}）".format(tp, fp, fn)))
    # 逐 server 三态精确一致（比 F1 更细：ok/unknown 也参与）
    three_state_diffs = _check_three_state(bundle)["diffs"]
    if three_state_diffs:
        diffs.append(_diff("baseline.parse.three_state", "逐 server 三态", "逐项一致", "{0} 条不符".format(len(three_state_diffs))))
    return _ok(diffs, metrics)


def _render_engine(bundle, reverse=False):
    """实算一遍引擎产物文本（`serialize.dumps` 即 `write_atomic` 的字节，K7）。

    `reverse=True` 时把事件流倒序后再聚合/归因——用于证明产物**与输入顺序无关**。
    """
    rules = bundle["rules"]
    max_error_chars = (rules.params.get("error_text") or {}).get("max_chars")
    events, report = pipeline.scan_home(bundle["home"], max_error_chars)
    if reverse:
        events = list(reversed(events))
    return {
        "events": serialize.dumps(pipeline.build_events_payload(events, report)),
        "aggregate": serialize.dumps(pipeline.aggregate_events(events, rules)),
        "attribute": serialize.dumps(pipeline.attribute_events(events, rules)),
    }


def _check_e2e_determinism(bundle):
    """端到端双跑逐字节一致（"双基线"之二）：两次独立运行的产物文本必须完全相同。

    `_injected_payloads` 是**探活专用接缝**：探活用它喂入两份不同的产物文本，
    以证伪"双跑一致"这条断言——否则该套件无法在不动真实代码的前提下被弄红。
    """
    diffs = []
    override = bundle.get("_injected_payloads")
    if override is not None:
        first, second = override
    else:
        first = _render_engine(bundle, reverse=False)
        second = _render_engine(bundle, reverse=True)
    metrics = {}
    for name in sorted(first):
        digest_one = _sha256(first[name])
        digest_two = _sha256(second.get(name, ""))
        metrics[name] = {"sha256_run1": digest_one, "sha256_run2": digest_two}
        if first[name] != second.get(name):
            diffs.append(_diff("baseline.e2e.byte_identity", name, "两次运行逐字节一致", "不一致", "确定性被破坏"))
    return _ok(diffs, metrics)


# ---------------------------------------------------------------------------
# 套件描述
# ---------------------------------------------------------------------------


class Suite(object):
    """一个对账套件：`check` 对账 + `probe` 注入缺陷 + `requirement` 判"未启用"。"""

    def __init__(self, suite_id, layer, title, check, probe, requirement=None):
        self.id = suite_id
        self.layer = layer
        self.title = title
        self.check = check
        self.probe = probe
        self.requirement = requirement


def _need_truth_servers(bundle):
    if not _truth_servers(bundle):
        return "真值未声明任何 server 维度"
    return None


def _need_effective_rules(bundle):
    if not bundle["rules"].effective_patterns():
        return "规则包无生效规则（门控无可演练样本）——'未启用'不得冒充通过"
    return None


def _need_retry_samples(bundle):
    if not any(declared["expected_retry_count"] > 0 for _source, declared in _truth_servers(bundle)):
        return "真值未声明任何重试型 server（重试口径无可演练样本）"
    return None


def _need_error_samples(bundle):
    if not bundle["agg"]["totals"]["calls_error"]:
        return "无失败调用样本（解析基线无可演练样本）"
    return None


def _need_manifest(bundle):
    if not bundle["manifest"].get("coverage"):
        return "manifest 未登记任何覆盖维度"
    return None


# ---------------------------------------------------------------------------
# 探活（每套件"故意弄坏 → 必须变红"）
# ---------------------------------------------------------------------------


def _with_agg_rows(bundle, rows):
    new = dict(bundle)
    agg = dict(bundle["agg"])
    agg["server_level"] = rows
    new["agg"] = agg
    return new


def _row_for(bundle, source, server):
    for row in bundle["agg"]["server_level"]:
        if row["source"] == source and row["server"] == server:
            return row
    return None


def _corrupt_agg_row(bundle, source, server, changes):
    """把某个 (source, server) 聚合行按 `changes` 改写，用于探活注入缺陷。

    注入值一律**从该行实算值派生**（不是写死的魔数），故口径改动后探活仍成立。
    """
    rows = []
    for row in bundle["agg"]["server_level"]:
        row = dict(row)
        if row["source"] == source and row["server"] == server:
            row.update(changes)
        rows.append(row)
    return _with_agg_rows(bundle, rows)


def _with_attr(bundle, attr):
    new = dict(bundle)
    new["attr"] = attr
    return new


def _probe_three_state(bundle):
    """注入缺陷：把一条 error 洗成 ok（等价于"把 is_error=True 判成 ok"）。"""
    row = _row_for(bundle, schema.SOURCE_CLAUDE_CODE, "fake-high-fail")
    return _corrupt_agg_row(
        bundle,
        schema.SOURCE_CLAUDE_CODE,
        "fake-high-fail",
        {"calls_ok": row["calls_ok"] + 1, "calls_error": row["calls_error"] - 1},
    )


def _probe_failure_rate(bundle):
    """注入缺陷：把 unknown 计入失败率分母（分母口径失效）。

    注入值 = 该行正确分母 + `calls_unknown`（即"若把 unknown 计入分母"的结果）。
    """
    row = _row_for(bundle, schema.SOURCE_CLAUDE_CODE, "fake-mid-fail")
    return _corrupt_agg_row(
        bundle,
        schema.SOURCE_CLAUDE_CODE,
        "fake-mid-fail",
        {"failure_rate_denominator": row["failure_rate_denominator"] + row["calls_unknown"]},
    )


def _probe_retry(bundle):
    """注入缺陷：给"零重试"的 server 凭空加一次重试。"""
    return _corrupt_agg_row(bundle, schema.SOURCE_CLAUDE_CODE, "fake-high-fail", {"retry_count": 1})


def _probe_token(bundle):
    """注入缺陷：把 Codex 会话级 token 摊到单次调用（造假结论）。"""
    return _corrupt_agg_row(
        bundle, schema.SOURCE_CODEX, "<codex>", {"token_samples": 1, "turn_token_avg": 1234.0}
    )


def _probe_duration(bundle):
    """注入缺陷：Claude 侧耗时改称"可得"（用不可得冒充可得）。"""
    return _corrupt_agg_row(
        bundle, schema.SOURCE_CLAUDE_CODE, "fake-low-fail", {"duration_available": True, "duration_samples": 3}
    )


def _probe_two_level(bundle):
    """注入缺陷：tool 级少一行 → server 级 rollup 对不上。"""
    new = dict(bundle)
    agg = dict(bundle["agg"])
    agg["tool_level"] = [dict(row) for row in bundle["agg"]["tool_level"][1:]]
    new["agg"] = agg
    return new


def _probe_category(bundle):
    """注入缺陷：把一条 timeout 命中挪进 other（分布与真值不符）。"""
    attr = bundle["attr"]
    by_server = []
    for row in attr["by_server"]:
        row = dict(row)
        if row["server"] == "fake-high-fail":
            categories = dict(row["categories"])
            categories["timeout"] = categories.get("timeout", 0) - 1
            categories[attribute_module.CATEGORY_OTHER] = categories.get(attribute_module.CATEGORY_OTHER, 0) + 1
            row["categories"] = categories
        by_server.append(row)
    return _with_attr(bundle, dict(attr, by_server=by_server))


def _probe_rule_gate(bundle):
    """注入缺陷：把未生效规则塞进计算路径（K10 门控失效）。"""
    attr = dict(bundle["attr"])
    inactive = [item["id"] for item in attr["ineffective_rules"]]
    assert inactive, "规则包里没有未生效规则，本探活无法注入（基准覆盖有洞）"
    attr["effective_rule_ids"] = list(attr["effective_rule_ids"]) + [inactive[0]]
    return _with_attr(bundle, attr)


def _probe_match_audit(bundle):
    """注入缺陷：把命中记录的 rule_id 改成未生效规则。"""
    attr = dict(bundle["attr"])
    inactive = [item["id"] for item in attr["ineffective_rules"]]
    matched = [dict(item) for item in attr["matched_patterns"]]
    assert matched and inactive, "无命中记录或无未生效规则，本探活无法注入"
    matched[0]["rule_id"] = inactive[0]
    attr["matched_patterns"] = matched
    return _with_attr(bundle, attr)


def _probe_manifest_coverage(bundle):
    """注入缺陷：把某个覆盖维度的采样数清零（双登记失效）。"""
    manifest = dict(bundle["manifest"])
    coverage = []
    for item in bundle["manifest"]["coverage"]:
        item = dict(item)
        if item.get("dimension") == "failure_mode":
            item["sampled_forms"] = 0
        coverage.append(item)
    manifest["coverage"] = coverage
    new = dict(bundle)
    new["manifest"] = manifest
    return new


def _probe_parse_baseline(bundle):
    """注入缺陷：把 Codex 侧错误计数少算一条 → F1 掉到 1 以下。"""
    row = None
    for candidate in bundle["agg"]["server_level"]:
        if candidate["source"] == schema.SOURCE_CODEX:
            row = candidate
    if row is None:
        return bundle
    return _corrupt_agg_row(bundle, schema.SOURCE_CODEX, row["server"], {"calls_error": row["calls_error"] - 1})


def _probe_e2e(bundle):
    """注入缺陷：让两次运行的产物文本出现一处字节差异。"""
    first = _render_engine(bundle, reverse=False)
    second = dict(first)
    second["aggregate"] = first["aggregate"] + " "
    new = dict(bundle)
    new["_injected_payloads"] = (first, second)
    return new


# ---------------------------------------------------------------------------
# 套件注册表（`--only` 白名单的唯一出处）
# ---------------------------------------------------------------------------

SUITES = (
    Suite("S-THREE-STATE", LAYER_SAMPLE, "三态计数逐 server 对账", _check_three_state, _probe_three_state, _need_truth_servers),
    Suite("S-FAILURE-RATE", LAYER_SAMPLE, "失败率与分子分母对账（分母不含 unknown）", _check_failure_rate, _probe_failure_rate, _need_truth_servers),
    Suite("S-RETRY-COUNT", LAYER_SAMPLE, "重试计数逐 server 对账", _check_retry_count, _probe_retry, _need_retry_samples),
    Suite("S-TOKEN", LAYER_SAMPLE, "token 四项分列与样本量口径对账", _check_token, _probe_token, None),
    Suite("S-DURATION", LAYER_SAMPLE, "耗时口径对账（Claude 不可得 / Codex 可得）", _check_duration, _probe_duration, None),
    Suite("S-TWO-LEVEL", LAYER_SAMPLE, "两级维度 rollup 与对账等式", _check_two_level, _probe_two_level, None),
    Suite("R-CATEGORY-DIST", LAYER_RULE, "失败分类分布逐 server 对账", _check_category_distribution, _probe_category, _need_truth_servers),
    Suite("R-RULE-GATE", LAYER_RULE, "规则生效门控与真值 rule_effective 对账", _check_rule_gate, _probe_rule_gate, _need_effective_rules),
    Suite("R-MATCH-AUDIT", LAYER_RULE, "命中规则/模式可审计且只来自生效规则", _check_match_audit, _probe_match_audit, None),
    Suite("C-MANIFEST-COVERAGE", LAYER_COVERAGE, "覆盖声明总数/采样数双登记（消费 manifest）", _check_manifest_coverage, _probe_manifest_coverage, _need_manifest),
    Suite("B-PARSE-RECONCILE", LAYER_BASELINE, "解析对账基线（计数级 F1 = 1）", _check_parse_baseline, _probe_parse_baseline, _need_error_samples),
    Suite("B-E2E-DETERMINISM", LAYER_BASELINE, "端到端双跑逐字节一致基线", _check_e2e_determinism, _probe_e2e, None),
)

SUITE_IDS = tuple(suite.id for suite in SUITES)


def suite_by_id(suite_id):
    for suite in SUITES:
        if suite.id == suite_id:
            return suite
    return None


def select_suites(only=None, check_only=False):
    """按 `--only` / `--check` 选套件。未知名 → `UsageError`（exit 2，用法与未知名）。"""
    if only is not None:
        suite = suite_by_id(only)
        if suite is None:
            raise exit_codes.UsageError(
                "未知基准套件：{0}（可用套件：{1}）".format(only, ", ".join(SUITE_IDS))
            )
        return (suite,)
    if check_only:
        return tuple(suite for suite in SUITES if suite.layer == LAYER_BASELINE)
    return SUITES


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------


def _run_suite(suite, bundle):
    """跑一个套件：先判"未启用"，再对账，再探活（探活必须变红）。"""
    result = {
        "id": suite.id,
        "layer": suite.layer,
        "title": suite.title,
        "status": STATUS_PASS,
        "not_enabled": False,
        "checks": 0,
        "diffs": [],
        "metrics": {},
        "notes": [],
        "probe": None,
    }
    note = suite.requirement(bundle) if suite.requirement else None
    if note:
        result["status"] = STATUS_NOT_ENABLED
        result["not_enabled"] = True
        result["notes"].append(note)
        return result

    outcome = suite.check(bundle)
    diffs = outcome["diffs"]
    result["diffs"] = diffs
    result["metrics"] = outcome["metrics"]
    result["checks"] = 1
    if diffs:
        result["status"] = STATUS_FAIL

    # 探活：把输入故意弄坏，同一套 check 必须报出差异（否则本套件是假门）
    corrupted = suite.probe(bundle)
    probe_outcome = suite.check(corrupted)
    detected = len(probe_outcome["diffs"]) > 0
    result["probe"] = {
        "detected": detected,
        "diffs": len(probe_outcome["diffs"]),
        "note": "注入缺陷后必须报出差异；未变红 = 该套件是假门",
    }
    if not detected:
        result["notes"].append("探活未变红：本套件对注入缺陷无反应（假门）")
        result["status"] = STATUS_FAIL
    return result


def run_bench(bundle=None, data_dir=None, home=None, rules_dir=None, only=None, check_only=False):
    """跑基准：返回 `(payload, exit_code)`。

    载荷含每套件的状态、差异逐条、探活结果，以及覆盖声明与判定。
    退出码三语义：0 达标 / 1 未达标（差异、未启用、或探活未变红）/ 2 用法与未知名。
    """
    selected = select_suites(only=only, check_only=check_only)
    if bundle is None:
        bundle = build_bundle(data_dir=data_dir, home=home, rules_dir=rules_dir)

    results = [_run_suite(suite, bundle) for suite in selected]

    failed = [item for item in results if item["status"] == STATUS_FAIL]
    not_enabled = [item for item in results if item["status"] == STATUS_NOT_ENABLED]
    total_diffs = sum(len(item["diffs"]) for item in results)
    probes_undetected = [item["id"] for item in results if item["probe"] is not None and not item["probe"]["detected"]]

    verdict = STATUS_PASS if not failed and not not_enabled and not probes_undetected else STATUS_FAIL

    manifest = bundle["manifest"]
    payload = {
        "schema": BENCH_SCHEMA,
        "data_dir": bundle["data_dir"],
        "home": bundle["home"],
        "selection": {"only": only, "check": bool(check_only)},
        "layers": sorted(set(suite.layer for suite in selected)),
        "suites": results,
        "totals": {
            "suites": len(results),
            "passed": len([item for item in results if item["status"] == STATUS_PASS]),
            "failed": len(failed),
            "not_enabled": len(not_enabled),
            "diffs": total_diffs,
            "probes_undetected": len(probes_undetected),
        },
        "coverage_declaration": {
            "declaration": manifest.get("declaration"),
            "dimensions": [
                {
                    "dimension": item.get("dimension"),
                    "required_forms": item.get("required_forms"),
                    "sampled_forms": item.get("sampled_forms"),
                    "items": len(item.get("items") or []),
                }
                for item in (manifest.get("coverage") or [])
            ],
            "totals": manifest.get("totals"),
            "note": "基准消费 manifest 的逐维度'总数/采样数'双登记；抽样覆盖，非穷举。",
        },
        "verdict": verdict,
        "coverage_note": (
            "引擎输出为**运行时实算**（重新扫描 + 聚合 + 归因），真值只提供期望值（K12）；"
            "每套件配可证伪探活（注入缺陷必须变红）；未启用套件不冒充通过（exit 1）。"
        ),
    }
    exit_code = exit_codes.EXIT_OK if verdict == STATUS_PASS else exit_codes.EXIT_FINDINGS
    return payload, exit_code
