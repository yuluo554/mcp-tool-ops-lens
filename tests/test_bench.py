"""模块 5 真值基准守门（M4 DoD 逐项落成可证伪断言）。

覆盖：
  · **对账**：引擎输出 vs 植入真值，全维度一致；差异逐条列出（不是只报"不一致"）
  · **分层**：样本驱动层（`S-*`）+ 规则驱动层（`R-*`）+ 覆盖层（`C-*`）+ 双基线层（`B-*`）
  · **`--only` 白名单**：套件注册进白名单；`--only NOPE` → exit 2
  · **每套件配可证伪探活**：注入缺陷 → 必报未达标（本文件对**全部 12 个套件**逐个验证探活变红）
  · **退出码三语义**（0/1/2）锁进测试
  · **空分母分支**：`not_enabled=true` + notes + exit 1（"未启用"不得冒充通过）
  · **覆盖声明"总数/采样数双登记"** + 显式"抽样覆盖非穷举"（基准消费 manifest）
  · **K12**：观测由基准运行时实算（真值库无观测字段；本模块不读真值的观测）
  · **双基线复跑**：解析对账基线（F1）+ e2e 双跑逐字节一致

变异验证（`tools/mutation_check.py`）：把某套件的探活摘掉 → 本文件"探活必红"断言必红。
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from opslens import bench  # noqa: E402
from opslens import config  # noqa: E402
from opslens import exit_codes  # noqa: E402
from opslens import schema  # noqa: E402
from opslens import serialize  # noqa: E402
from opslens.cli import main  # noqa: E402


@pytest.fixture(scope="module")
def bundle():
    return bench.build_bundle()


@pytest.fixture(scope="module")
def payload():
    result, code = bench.run_bench()
    assert code == exit_codes.EXIT_OK, "基准未达标：{0}".format(result["totals"])
    return result


def _suite(payload, suite_id):
    for item in payload["suites"]:
        if item["id"] == suite_id:
            return item
    raise AssertionError("套件缺失：{0}".format(suite_id))


def _write_minimal_rules(directory, rules):
    serialize.write_json(os.path.join(directory, "thresholds.json"), {"remove_candidate": {"failure_rate_gte": 0.5}})
    serialize.write_json(
        os.path.join(directory, "params.json"), {"retry": {"window_seconds": 120}, "rate_precision": 6}
    )
    serialize.write_json(
        os.path.join(directory, "failure_patterns.json"),
        {"categories": ["timeout", "permission_denied", "invalid_args", "content_refusal", "other"], "rules": rules},
    )


# ---------------------------------------------------------------------------
# 对账：全维度一致 + 差异逐条列出
# ---------------------------------------------------------------------------


def test_bench_passes_on_frozen_synthetic_data(payload):
    """冻结合成数据上，全部套件对账一致（引擎输出 == 植入真值）。"""
    assert payload["verdict"] == bench.STATUS_PASS
    assert payload["totals"]["failed"] == 0
    assert payload["totals"]["diffs"] == 0
    assert payload["totals"]["suites"] >= 10, "套件数过少，对账覆盖面不足"


def test_every_dimension_is_reconciled(payload):
    """DoD 要求的维度都必须在选中套件里：三态 / 失败率 / 重试 / 失败模式分布 / 两级维度。"""
    ids = [item["id"] for item in payload["suites"]]
    for required in (
        "S-THREE-STATE",
        "S-FAILURE-RATE",
        "S-RETRY-COUNT",
        "R-CATEGORY-DIST",
        "S-TWO-LEVEL",
    ):
        assert required in ids, "缺对账维度：{0}".format(required)


def test_all_probes_turn_red(payload):
    """**每套件探活必须变红**（注入缺陷 → 报出差异）；未变红即假门，基准自判未达标。"""
    undetected = [item["id"] for item in payload["suites"] if not item["probe"]["detected"]]
    assert undetected == [], "以下套件的探活未变红（假门）：{0}".format(undetected)
    for item in payload["suites"]:
        assert item["probe"]["diffs"] >= 1, "{0} 探活未报出任何差异".format(item["id"])


def test_probe_is_load_bearing_for_every_suite(bundle):
    """**逐个套件**独立验证：把输入弄坏后该套件必须报差异（不能只靠总闸门）。

    这是 DoD「每套件配可证伪探活」的最硬形态：对全部注册套件逐个跑探活并断言。
    """
    checked = 0
    for suite in bench.SUITES:
        if suite.requirement is not None and suite.requirement(bundle):
            continue  # 未启用套件无探活意义（由 not_enabled 分支覆盖）
        corrupted = suite.probe(bundle)
        assert corrupted is not bundle, "{0} 的探活没有改变输入".format(suite.id)
        diffs = suite.check(corrupted)["diffs"]
        assert diffs, "{0} 对注入缺陷无反应（探活是假门）".format(suite.id)
        checked += 1
    assert checked >= 10, "逐个验证的套件数过少（{0}）".format(checked)


def test_probe_verdict_is_derived_from_rerunning_the_check(bundle):
    """**探活判定必须是"重跑 check 得出的"，不是常量**。

    手法：造一个**探活为空操作**的套件（probe 原样返回输入）→ `_run_suite` 必须报
    `detected=False` 且套件未达标。若 `detected` 被写成恒真（变异项 25），本断言立刻变红。
    """
    noop = bench.Suite(
        "S-NOOP-PROBE",
        bench.LAYER_SAMPLE,
        "探活空操作（用于证伪探活判定）",
        bench._check_three_state,
        lambda bundle_: bundle_,
        None,
    )
    result = bench._run_suite(noop, bundle)
    assert result["probe"]["detected"] is False, "空操作探活被判为已检出（探活判定是常量）"
    assert result["status"] == bench.STATUS_FAIL
    assert result["notes"], "探活未变红必须留下说明"


def test_probe_detector_actually_detects(bundle):
    """探针自证：三态套件的探活必须把"error 洗成 ok"抓出来（否则守门可能空转）。"""
    suite = bench.suite_by_id("S-THREE-STATE")
    corrupted = suite.probe(bundle)
    diffs = suite.check(corrupted)["diffs"]
    dimensions = set(item["dimension"] for item in diffs)
    assert any(item.startswith("three_state") for item in dimensions), (
        "探活注入的缺陷未被三态维度捕获：{0}".format(dimensions)
    )


def test_diffs_are_listed_item_by_item():
    """差异**逐条列出**（DoD 明写"不能只报不一致"）：每条含维度/键/期望/实际。"""
    bundle = bench.build_bundle()
    truth = bundle["truth"]
    claude = dict(truth["claude"])
    servers = [dict(item) for item in claude["servers"]]
    servers[0]["calls_error"] = 999  # 与引擎实算值必然不符
    claude["servers"] = servers
    corrupted_truth = dict(truth, claude=claude)
    broken = dict(bundle, truth=corrupted_truth)

    payload, code = bench.run_bench(bundle=broken, only="S-THREE-STATE")
    assert code == exit_codes.EXIT_FINDINGS
    diffs = payload["suites"][0]["diffs"]
    assert diffs, "篡改真值后未报出差异"
    for item in diffs:
        assert item["dimension"] and item["key"] != "" and "expected" in item and "actual" in item
    assert any(item["expected"] == 999 for item in diffs), "差异未列出期望值"


# ---------------------------------------------------------------------------
# 分层：样本驱动 + 规则驱动
# ---------------------------------------------------------------------------


def test_layers_are_declared_and_both_present(payload):
    layers = set(item["layer"] for item in payload["suites"])
    assert bench.LAYER_SAMPLE in layers, "缺样本驱动层"
    assert bench.LAYER_RULE in layers, "缺规则驱动层"
    assert payload["layers"] == sorted(layers)


def test_sample_layer_drives_from_synthetic_logs(payload):
    """样本驱动层：直接对合成日志的三态/失败率/重试对账（不只跑单元级）。"""
    ids = [item["id"] for item in payload["suites"] if item["layer"] == bench.LAYER_SAMPLE]
    assert "S-THREE-STATE" in ids and "S-FAILURE-RATE" in ids and "S-RETRY-COUNT" in ids


def test_rule_layer_reconciles_gate_and_categories(payload):
    """规则驱动层：规则生效门控 + 失败分类分布对账（未生效规则落 other 的期望）。"""
    ids = [item["id"] for item in payload["suites"] if item["layer"] == bench.LAYER_RULE]
    assert "R-RULE-GATE" in ids and "R-CATEGORY-DIST" in ids
    gate = _suite(payload, "R-RULE-GATE")
    assert gate["status"] == bench.STATUS_PASS
    # 未生效规则必须逐条带原因
    for item in bench.build_bundle()["attr"]["ineffective_rules"]:
        assert item["reasons"]


def test_category_other_absorbs_ineffective_rule_coverage(bundle):
    """未生效规则（F-REFUSE-1）覆盖的失败必须落 `other`（真值声明 rule_effective=false）。"""
    declared = dict((item["server"], item) for item in bundle["truth"]["claude"]["servers"])
    low = declared["fake-low-fail"]
    assert low["failure_modes"]["content_refusal"]["rule_effective"] is False
    by_attr = dict(((row["source"], row["server"]), row) for row in bundle["attr"]["by_server"])
    row = by_attr[("claude_code", "fake-low-fail")]
    assert row["categories"]["other"] == 1, "未生效规则覆盖的失败未落 other"
    assert row["categories"]["content_refusal"] == 0


# ---------------------------------------------------------------------------
# --only 白名单与退出码三语义
# ---------------------------------------------------------------------------


def test_only_whitelist_is_registry_derived():
    """`--only` 白名单直接来自套件注册表（不手写第二份清单）。"""
    assert bench.SUITE_IDS == tuple(suite.id for suite in bench.SUITES)
    assert len(bench.SUITE_IDS) == len(set(bench.SUITE_IDS)), "套件 id 重复"


def test_unknown_only_is_usage_error():
    """`--only NOPE` → 用法与未知名 → exit 2（DoD 可演示物）。"""
    with pytest.raises(exit_codes.UsageError) as excinfo:
        bench.select_suites(only="NOPE")
    assert excinfo.value.exit_code == exit_codes.EXIT_USAGE


def test_unknown_only_via_cli_is_exit_2(rules_dir, capsys):
    code = main(["bench", "--only", "NOPE", "--rules-dir", rules_dir])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_USAGE
    assert "未知基准套件" in captured.err


def test_known_only_selects_exactly_that_suite(payload):
    result, code = bench.run_bench(only="S-TOKEN")
    assert code == exit_codes.EXIT_OK
    assert [item["id"] for item in result["suites"]] == ["S-TOKEN"]
    assert result["selection"]["only"] == "S-TOKEN"


def test_check_only_selects_baseline_layer():
    """`--check` 只跑双基线套件（解析对账 + e2e 双跑）。"""
    result, code = bench.run_bench(check_only=True)
    assert code == exit_codes.EXIT_OK
    assert result["layers"] == [bench.LAYER_BASELINE]
    ids = [item["id"] for item in result["suites"]]
    assert "B-PARSE-RECONCILE" in ids and "B-E2E-DETERMINISM" in ids


def test_exit_code_semantics_are_locked():
    """退出码三语义：0 达标 / 1 未达标 / 2 用法与未知名（在 exit_codes 里的取值）。"""
    assert exit_codes.EXIT_OK == 0
    assert exit_codes.EXIT_FINDINGS == 1
    assert exit_codes.EXIT_USAGE == 2
    _payload, code = bench.run_bench()
    assert code == exit_codes.EXIT_OK


def test_cli_bench_returns_exit_0_on_frozen_data(rules_dir, tmp_out, capsys):
    """可演示物：`opslens bench` 出对账报告，退出码 0。"""
    out = os.path.join(tmp_out, "bench.json")
    code = main(["bench", "--rules-dir", rules_dir, "--out", out])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_OK
    assert "基准达标" in captured.out
    assert os.path.isfile(out)
    payload = serialize.read_json(out)
    assert payload["schema"] == bench.BENCH_SCHEMA
    assert payload["verdict"] == bench.STATUS_PASS


def test_cli_bench_writes_byte_identical_report_on_two_runs(rules_dir, tmp_out):
    """确定性：两次 `bench --out` 的产物逐字节一致（K7）。"""
    first = os.path.join(tmp_out, "a.json")
    second = os.path.join(tmp_out, "b.json")
    assert main(["bench", "--rules-dir", rules_dir, "--out", first]) == exit_codes.EXIT_OK
    assert main(["bench", "--rules-dir", rules_dir, "--out", second]) == exit_codes.EXIT_OK
    with open(first, "rb") as handle:
        raw_one = handle.read()
    with open(second, "rb") as handle:
        raw_two = handle.read()
    assert raw_one == raw_two, "基准报告双跑不一致（确定性被破坏）"


# ---------------------------------------------------------------------------
# 空分母分支："未启用"不得冒充通过
# ---------------------------------------------------------------------------


def test_not_enabled_when_no_effective_rules(tmp_out):
    """空规则包（无生效规则）→ 规则驱动套件 `not_enabled=true` + notes + exit 1。"""
    _write_minimal_rules(tmp_out, [])
    bundle = bench.build_bundle(rules_dir=tmp_out)
    payload, code = bench.run_bench(bundle=bundle, only="R-RULE-GATE")
    item = payload["suites"][0]
    assert item["status"] == bench.STATUS_NOT_ENABLED
    assert item["not_enabled"] is True
    assert item["notes"], "未启用必须带 notes 说明原因"
    assert code == exit_codes.EXIT_FINDINGS, "未启用必须以 exit 1 退出（不得冒充通过）"
    assert payload["verdict"] == bench.STATUS_FAIL


def test_not_enabled_suite_is_not_counted_as_passed(tmp_out):
    """未启用套件不得计入通过数（防"空分母冒充通过"）。"""
    _write_minimal_rules(tmp_out, [])
    bundle = bench.build_bundle(rules_dir=tmp_out)
    payload, _code = bench.run_bench(bundle=bundle, only="R-RULE-GATE")
    assert payload["totals"]["passed"] == 0
    assert payload["totals"]["not_enabled"] == 1


def test_no_error_samples_marks_parse_baseline_not_enabled(bundle):
    """无失败样本时解析基线无可演练样本 → not_enabled（而非"F1=1 假绿"）。"""
    suite = bench.suite_by_id("B-PARSE-RECONCILE")
    empty = dict(bundle)
    agg = dict(bundle["agg"])
    agg["totals"] = dict(agg["totals"], calls_error=0)
    empty["agg"] = agg
    assert suite.requirement(empty) is not None, "无失败样本时未判 not_enabled"


def test_requirement_returns_none_when_samples_exist(bundle):
    """阳性对照：样本齐备时不得误判 not_enabled（否则上面的断言是空转）。"""
    for suite in bench.SUITES:
        if suite.requirement is None:
            continue
        assert suite.requirement(bundle) is None, "{0} 误判未启用".format(suite.id)


# ---------------------------------------------------------------------------
# 覆盖声明：总数/采样数双登记 + 显式"抽样覆盖非穷举"（消费 manifest）
# ---------------------------------------------------------------------------


def test_coverage_declaration_consumes_manifest(payload):
    """基准消费 manifest：覆盖声明含逐维度"总数/采样数"双登记 + 非穷举声明。"""
    declaration = payload["coverage_declaration"]
    assert "非穷举" in (declaration["declaration"] or ""), "覆盖声明必须显式写出'抽样覆盖非穷举'"
    assert declaration["dimensions"], "缺逐维度登记"
    for item in declaration["dimensions"]:
        assert item["required_forms"] >= 1
        assert item["sampled_forms"] >= item["required_forms"], "{0} 采样数未达标".format(item["dimension"])
        assert item["items"] >= 1, "{0} 缺逐项登记".format(item["dimension"])


def test_coverage_suite_flags_missing_non_exhaustive_declaration(bundle):
    """可证伪：manifest 去掉"非穷举"声明 → 覆盖套件必须报出差异（该检查不是摆设）。"""
    manifest = dict(bundle["manifest"])
    manifest["declaration"] = "本基准覆盖全部真实世界形态。"
    broken = dict(bundle, manifest=manifest)
    suite = bench.suite_by_id("C-MANIFEST-COVERAGE")
    diffs = suite.check(broken)["diffs"]
    assert any(item["dimension"] == "coverage.declaration" for item in diffs), (
        "非穷举声明缺失未被检出：{0}".format(diffs)
    )


def test_coverage_suite_reconciles_engine_totals_against_manifest(bundle):
    """覆盖套件必须把引擎汇总数与 manifest 声明的总数对账（不是只复述 manifest）。"""
    suite = bench.suite_by_id("C-MANIFEST-COVERAGE")
    assert suite.check(bundle)["diffs"] == []
    corrupted = suite.probe(bundle)
    assert suite.check(corrupted)["diffs"], "覆盖套件对『采样数清零』无反应"


def test_manifest_coverage_dimensions_are_required(payload):
    """DoD 要求的最低覆盖维度都要在声明里可见。"""
    names = [item["dimension"] for item in payload["coverage_declaration"]["dimensions"]]
    for required in ("server_failure_rate", "failure_mode", "three_state", "threshold_boundary", "reverse_case"):
        assert required in names, "覆盖声明缺维度 {0}".format(required)


# ---------------------------------------------------------------------------
# K12：观测由基准运行时实算
# ---------------------------------------------------------------------------


def test_engine_output_is_computed_at_runtime_not_read_from_truth(bundle):
    """观测实算：引擎输出必须来自真实引擎调用，与真值库无数据通路。

    手法：篡改真值的期望值**不影响**引擎实算输出（`agg` / `attr` / `events` 不变）——
    若基准偷读真值当观测，两者会一起变。
    """
    truth = bundle["truth"]
    claude = dict(truth["claude"])
    servers = [dict(item) for item in claude["servers"]]
    servers[0]["calls_error"] = 999
    claude["servers"] = servers
    broken = dict(bundle, truth=dict(truth, claude=claude))
    assert broken["agg"] == bundle["agg"], "真值篡改影响了引擎实算输出（观测疑似读自真值）"
    assert broken["attr"] == bundle["attr"]


def test_truth_library_has_no_observed_fields(bundle):
    """真值库只存输入与期望（K12）：出现观测类字段即红。"""

    def _keys(node):
        if isinstance(node, dict):
            for key, value in node.items():
                yield key
                for nested in _keys(value):
                    yield nested
        elif isinstance(node, list):
            for item in node:
                for nested in _keys(item):
                    yield nested

    offenders = [key for key in _keys(bundle["truth"]) if "observed" in key.lower() or "actual" in key.lower()]
    assert offenders == [], "真值库出现观测类字段：{0}".format(offenders)


def test_bench_module_does_not_read_truth_observation_keys():
    """基准源码不得出现 `observed` / `actual` 取值路径（防"冻结观测"同族错误）。"""
    path = os.path.join(SRC_DIR, "opslens", "bench.py")
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    # "actual" 只作为差异条目的**输出键**（我们写入的），不得作为真值读取键
    assert "truth[\"observed" not in source and "truth['observed" not in source
    assert '"observed_' not in source


# ---------------------------------------------------------------------------
# 双基线：解析对账 F1 + e2e 双跑逐字节一致
# ---------------------------------------------------------------------------


def test_parse_baseline_f1_is_one(payload):
    """解析对账基线：计数级 F1 == 1（精确植入真值下等价于逐 server 错误计数完全一致）。"""
    item = _suite(payload, "B-PARSE-RECONCILE")
    metrics = item["metrics"]
    assert metrics["f1"] == 1.0, "解析对账 F1 未达 1：{0}".format(metrics)
    assert metrics["precision"] == 1.0 and metrics["recall"] == 1.0
    assert metrics["confusion"] == {"tp": metrics["confusion"]["tp"], "fp": 0, "fn": 0}


def test_parse_baseline_f1_drops_when_engine_is_wrong(bundle):
    """可证伪：把引擎错误计数改坏 → F1 必须掉到 1 以下，且**产出差异条目**。

    断言必须打在 `check()` 的 `diffs` 上（不只打 `metrics`）——变异项 30 把
    `if f1 != 1.0` 改成恒假时，只有 `diffs` 会消失，`metrics` 仍如实反映坏 F1。
    """
    suite = bench.suite_by_id("B-PARSE-RECONCILE")
    corrupted = suite.probe(bundle)
    outcome = suite.check(corrupted)
    assert outcome["metrics"]["f1"] != 1.0, "F1 对注入缺陷无反应（基线是假门）"
    assert outcome["metrics"]["confusion"]["fn"] >= 1 or outcome["metrics"]["confusion"]["fp"] >= 1
    assert any(item["dimension"] == "baseline.parse.f1" for item in outcome["diffs"]), (
        "F1 未达 1 却未产出差异条目：{0}".format(outcome["diffs"])
    )


def test_parse_baseline_reports_no_diff_when_f1_is_one(bundle):
    """阳性对照：F1 == 1 时不得产出 `baseline.parse.f1` 差异（否则上面是空转）。"""
    suite = bench.suite_by_id("B-PARSE-RECONCILE")
    outcome = suite.check(bundle)
    assert outcome["metrics"]["f1"] == 1.0
    assert not any(item["dimension"] == "baseline.parse.f1" for item in outcome["diffs"])


def test_e2e_determinism_is_byte_identical(payload):
    """e2e 双跑逐字节一致：两次独立运行的产物 sha256 必须相同。"""
    item = _suite(payload, "B-E2E-DETERMINISM")
    assert item["status"] == bench.STATUS_PASS
    for name, digest in item["metrics"].items():
        assert digest["sha256_run1"] == digest["sha256_run2"], "{0} 双跑不一致".format(name)


def test_e2e_determinism_detects_byte_difference(bundle):
    """可证伪：让两次产物差一个字节 → 该套件必须报差异。"""
    suite = bench.suite_by_id("B-E2E-DETERMINISM")
    corrupted = suite.probe(bundle)
    diffs = suite.check(corrupted)["diffs"]
    assert diffs, "双跑字节差异未被检出（基线是假门）"


def test_render_engine_output_is_order_independent(bundle):
    """e2e 基线的机理自证：正序与倒序输入产出同一字节文本。"""
    forward = bench._render_engine(bundle, reverse=False)
    backward = bench._render_engine(bundle, reverse=True)
    assert forward == backward, "产物依赖输入顺序（确定性被破坏）"


def test_baseline_layer_is_reproducible_across_process_runs():
    """双基线可复跑：两次独立 `run_bench(check_only=True)` 结果相同。"""
    first, code_one = bench.run_bench(check_only=True)
    second, code_two = bench.run_bench(check_only=True)
    assert code_one == code_two == exit_codes.EXIT_OK
    assert serialize.dumps(first) == serialize.dumps(second)


# ---------------------------------------------------------------------------
# 扫描面与结构
# ---------------------------------------------------------------------------


def test_scan_face_is_not_empty(bundle):
    """扫描面非空自证：防"目录写错 → 扫 0 条 → 全绿"。"""
    assert bundle["events"], "扫描面为空"
    assert bundle["agg"]["server_level"], "聚合维度为空"
    assert bundle["attr"]["totals"]["calls_error"] >= 1, "无失败样本"


def test_truth_declares_every_engine_server(bundle):
    """真值声明的 server 必须与引擎实际产出的 server 一一对应（防对账面有洞）。"""
    truth_keys = set((source, declared["server"]) for source, declared in bench._truth_servers(bundle))
    engine_keys = set((row["source"], row["server"]) for row in bundle["agg"]["server_level"])
    assert truth_keys == engine_keys, "真值与引擎的 server 面不一致：{0}".format(truth_keys ^ engine_keys)


def test_codex_side_is_covered(bundle):
    """Codex 侧必须进基准（跨源不混算也要对账）。"""
    assert any(row["source"] == schema.SOURCE_CODEX for row in bundle["agg"]["server_level"])
