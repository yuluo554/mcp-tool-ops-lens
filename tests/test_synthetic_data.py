"""合成数据与生成器守门（M1 DoD 逐项落成可证伪断言）。

纪律要点：
  · `--check` 位级一致（同 seed 重生成 == 盘中冻结产物）。
  · `truth.json` 只存"输入与期望"：出现 `observed_*` / `engine_output` 一类字段即红
    （冻结观测会让"引擎全坏也全绿"）。
  · 覆盖度 manifest 必须"总数/采样数"双登记。
  · 三态（ok / error / unknown）在合成日志里真实存在，且 unknown 是"字段缺失"形态。
  · server 名一律 `fake-*` 白名单。

变异验证（本文件已实测）：把 truth 的 `expected_failure_rate` 改名成
`observed_failure_rate` → `test_truth_has_no_observed_fields` 必红。
"""

import json
import os
import re
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(REPO_ROOT, "tools")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")

if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
if os.path.join(REPO_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

import gen_synthetic_logs as gen  # noqa: E402

REQUIRED_MODES = ("timeout", "permission_denied", "invalid_args", "content_refusal")


@pytest.fixture(scope="module")
def outputs():
    """重生成产物（不写盘）：[(相对路径, 文本)]。"""
    return gen.build_outputs()


@pytest.fixture(scope="module")
def truth():
    with open(os.path.join(SYNTHETIC_DIR, gen.TRUTH_FILE), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def manifest():
    with open(os.path.join(SYNTHETIC_DIR, gen.MANIFEST_FILE), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_claude_lines():
    path = os.path.join(SYNTHETIC_DIR, gen.CLAUDE_LOG)
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _read_codex_lines():
    path = os.path.join(SYNTHETIC_DIR, gen.CODEX_LOG)
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _parse_jsonl(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _regenerated_lines(outputs, relative):
    for name, text in outputs:
        if name == relative:
            return _parse_jsonl(text)
    raise AssertionError("产物缺失：{0}".format(relative))


def _three_state_counts(rows):
    """统计 tool_result 的 is_error 三态（true / false / 字段缺失）。"""
    seen = {"true": 0, "false": 0, "missing": 0}
    for row in rows:
        if row.get("type") != "user":
            continue
        for block in (row.get("message") or {}).get("content") or []:
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            if "is_error" not in block:
                seen["missing"] += 1
            elif block["is_error"] is True:
                seen["true"] += 1
            elif block["is_error"] is False:
                seen["false"] += 1
    return seen


# ---------------------------------------------------------------------------
# 位级确定性
# ---------------------------------------------------------------------------


def test_artifacts_exist_on_disk():
    for relative in (gen.CLAUDE_LOG, gen.CODEX_LOG, gen.TRUTH_FILE, gen.MANIFEST_FILE):
        assert os.path.isfile(os.path.join(SYNTHETIC_DIR, relative)), "缺产物 {0}".format(relative)


def test_regeneration_is_byte_identical_to_frozen_artifacts(outputs):
    """--check 通路的核心性质：重生成 == 盘中冻结产物（逐字节）。"""
    mismatches = gen.check_outputs(SYNTHETIC_DIR, outputs)
    assert mismatches == [], "位级不一致：{0}".format(mismatches)


def test_check_detects_mismatch(tmp_out):
    """可证伪自证：盘中内容被改动时 --check 必须报不一致（否则是假门）。"""
    gen.write_outputs(tmp_out, gen.build_outputs())
    assert gen.check_outputs(tmp_out, gen.build_outputs()) == []

    target = os.path.join(tmp_out, gen.TRUTH_FILE)
    with open(target, "r", encoding="utf-8") as handle:
        text = handle.read()
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(text.replace("20261016", "20261017", 1))

    mismatches = gen.check_outputs(tmp_out, gen.build_outputs())
    assert mismatches, "--check 未检出被篡改的产物：位级守门失效"


def test_two_builds_in_process_are_identical():
    assert gen.build_outputs() == gen.build_outputs()


def test_check_returns_findings_code_on_mismatch(tmp_out, capsys):
    """CLI 通路：--check 不一致 → exit 1（检出问题），一致 → exit 0。"""
    from opslens import exit_codes

    gen.write_outputs(tmp_out, gen.build_outputs())
    assert gen.main(["--out", tmp_out, "--check"]) == exit_codes.EXIT_OK
    capsys.readouterr()

    with open(os.path.join(tmp_out, gen.MANIFEST_FILE), "w", encoding="utf-8") as handle:
        handle.write("{}\n")
    assert gen.main(["--out", tmp_out, "--check"]) == exit_codes.EXIT_FINDINGS
    assert "不一致" in capsys.readouterr().err


def test_artifacts_have_no_cr_and_end_with_lf():
    for relative in (gen.CLAUDE_LOG, gen.CODEX_LOG, gen.TRUTH_FILE, gen.MANIFEST_FILE):
        with open(os.path.join(SYNTHETIC_DIR, relative), "rb") as handle:
            raw = handle.read()
        assert b"\r" not in raw, "{0} 含 CR".format(relative)
        assert raw.endswith(b"\n"), "{0} 缺结尾换行".format(relative)


def test_artifacts_contain_no_absolute_local_paths_or_credentials():
    """合成产物不得含本机绝对路径或凭据形态的值（隐私红线）。

    真实 server 名的扫描在 tests/test_privacy.py；此处只管产物本体里
    不该出现的"路径/凭据"两类值。
    """
    path_pattern = re.compile(r"[A-Za-z]:[\\/]{1,2}(Users|Windows|ProgramData|Program Files)", re.I)
    # 只按"凭据值形态"扫描；键名本身的守门在 tests/test_privacy.py
    cred_pattern = re.compile(r"(sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9._-]{16,})")
    scanned = 0
    for relative in (gen.CLAUDE_LOG, gen.CODEX_LOG, gen.TRUTH_FILE, gen.MANIFEST_FILE):
        with open(os.path.join(SYNTHETIC_DIR, relative), "r", encoding="utf-8") as handle:
            text = handle.read()
        scanned += 1
        assert not path_pattern.search(text), "{0} 含本机绝对路径".format(relative)
        assert not cred_pattern.search(text), "{0} 含凭据形态的值".format(relative)
    assert scanned == 4, "扫描面异常：{0}".format(scanned)


# ---------------------------------------------------------------------------
# 真值库只存"输入与期望"
# ---------------------------------------------------------------------------


def _all_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            for nested in _all_keys(value):
                yield nested
    elif isinstance(node, list):
        for item in node:
            for nested in _all_keys(item):
                yield nested


def test_truth_has_no_observed_fields(truth):
    """真值库出现"观测"即红：冻结观测会让引擎全坏也全绿（K12）。"""
    offenders = [
        key
        for key in _all_keys(truth)
        if "observed" in key.lower() or "engine_output" in key.lower() or key.lower().startswith("actual")
    ]
    assert offenders == [], "真值库出现观测类字段：{0}".format(sorted(set(offenders)))


def test_truth_top_level_keys_are_inputs_and_expectations_only(truth):
    allowed = {
        "seed",
        "generator",
        "note",
        "rules_snapshot",
        "claude",
        "codex",
        "boundary_cases",
        "reverse_cases",
        "three_state",
    }
    assert set(truth) <= allowed, "真值库出现计划外顶层键：{0}".format(sorted(set(truth) - allowed))


def test_truth_and_manifest_have_no_generation_timestamp(truth, manifest):
    """产物不得带"生成时刻"（否则双跑不可能逐字节一致）。"""
    for name, payload in (("truth", truth), ("manifest", manifest)):
        keys = [key.lower() for key in _all_keys(payload)]
        bad = [key for key in keys if key in ("generated_at", "generated", "date", "timestamp", "time")]
        assert bad == [], "{0} 含生成时刻字段：{1}".format(name, bad)


def test_truth_declares_expected_values_but_not_observations(truth):
    for server in truth["claude"]["servers"]:
        assert "expected_failure_rate" in server
        assert "expected_suggestion" in server
        assert server["calls_ok"] + server["calls_error"] + server["calls_unknown"] == server["calls_total"]


def test_truth_failure_rate_denominator_excludes_unknown(truth):
    """K1：失败率分母 = ok + error，不含 unknown。"""
    precision = truth["rules_snapshot"]["rate_precision"]
    for server in truth["claude"]["servers"]:
        denominator = server["calls_ok"] + server["calls_error"]
        expected = None if denominator == 0 else round(float(server["calls_error"]) / denominator, precision)
        assert server["expected_failure_rate"] == expected, server["server"]


# ---------------------------------------------------------------------------
# 覆盖度 manifest：总数/采样数双登记
# ---------------------------------------------------------------------------


def test_manifest_declares_sampling_not_exhaustive(manifest):
    assert "非穷举" in manifest["declaration"]


def test_manifest_coverage_double_registers_totals_and_samples(manifest):
    dimensions = dict((item["dimension"], item) for item in manifest["coverage"])
    expected = ("server_failure_rate", "failure_mode", "three_state", "threshold_boundary", "reverse_case")
    for name in expected:
        assert name in dimensions, "manifest 缺维度 {0}".format(name)
        item = dimensions[name]
        assert item["required_forms"] >= 1
        assert item["sampled_forms"] >= item["required_forms"], "{0} 采样数未达标".format(name)
        assert item["items"], "{0} 缺逐项登记".format(name)
    # 每个 failure_mode 项都要有采样数（不是只登记形态名）
    for entry in dimensions["failure_mode"]["items"]:
        assert entry["sampled_calls"] >= 1, "{0} 无采样".format(entry["form"])


def test_manifest_registers_four_server_shapes_and_four_modes(manifest):
    dimensions = dict((item["dimension"], item) for item in manifest["coverage"])
    assert dimensions["server_failure_rate"]["sampled_forms"] == 4
    assert dimensions["failure_mode"]["sampled_forms"] == 4
    assert dimensions["three_state"]["sampled_forms"] == 3


def test_manifest_totals_match_truth(manifest, truth):
    claude_total = sum(s["calls_total"] for s in truth["claude"]["servers"])
    assert manifest["totals"]["claude_calls"] == claude_total
    assert manifest["totals"]["codex_calls"] == truth["codex"]["calls_total"]


def test_manifest_registers_rules_pack_effectiveness(manifest):
    rules = manifest["rules_pack"]
    assert rules["total_rules"] >= 1
    assert rules["effective_rules"] < rules["total_rules"], "本机实测存在 0 样例规则，应有未生效项"
    ids = [rule["id"] for rule in rules["rules"]]
    assert "F-REFUSE-1" in ids


def test_synthetic_error_texts_match_their_declared_rule_patterns():
    """规则表声明的 synthetic_coverage 必须可验证：被点名的 server 里确有其模式命中的失败记录。

    这让"覆盖度登记"成为可证伪事实，而不是自述；同时**不**把合成文本写进
    verified_samples（那会构成自证循环）。
    """
    from opslens import config as opslens_config

    rules = opslens_config.load_rules()
    rows = _read_claude_lines()
    call_server = {}
    for row in rows:
        if row.get("type") == "assistant":
            for block in (row.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block["name"]
                    call_server[block["id"]] = name.split("__")[1]

    errors_by_server = {}
    for row in rows:
        if row.get("type") != "user":
            continue
        for block in (row.get("message") or {}).get("content") or []:
            if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                continue
            if block.get("is_error") is not True:
                continue
            server = call_server.get(block["tool_use_id"], "?")
            errors_by_server.setdefault(server, []).append(str(block.get("content") or ""))

    checked = 0
    for rule in rules.patterns["rules"]:
        coverage = rule.get("synthetic_coverage") or {}
        for server in coverage.get("claude_servers") or []:
            texts = errors_by_server.get(server) or []
            matched = any(
                re.search(pattern, text)
                for text in texts
                for pattern in rule["patterns"]
            )
            assert matched, (
                "{0} 声明由 {1} 演练，但该 server 的失败记录无模式命中（覆盖度登记不可验证）".format(
                    rule["id"], server
                )
            )
            checked += 1
    assert checked >= 4, "覆盖度登记过少（{0} 项），断言可能空转".format(checked)


def test_effective_rules_have_at_least_one_synthetic_exercise():
    """每条生效规则都必须在合成日志里被演练过（否则基准覆盖有洞）。"""
    from opslens import config as opslens_config

    rules = opslens_config.load_rules()
    covered_categories = set()
    for rule in rules.patterns["rules"]:
        coverage = rule.get("synthetic_coverage") or {}
        if coverage.get("claude_servers") or coverage.get("codex_calls"):
            covered_categories.add(rule["category"])
    for rule in rules.effective_patterns():
        assert rule["category"] in covered_categories, "生效规则 {0} 未被合成日志演练".format(rule["id"])


# ---------------------------------------------------------------------------
# 合成日志保真度：三态 / 配对 / 命名
# ---------------------------------------------------------------------------


def test_claude_log_contains_all_three_states(outputs):
    """三态各 ≥1，且 unknown 是"字段缺失"形态（不是 false）。

    断言必须同时打在**盘中冻结产物**与**重生成结果**两层上：只查盘中产物时，
    生成器把缺失态写成 is_error=false 的变异不会被发现（变异验证实测抓出过）。
    """
    for label, rows in (
        ("冻结产物", _read_claude_lines()),
        ("重生成", _regenerated_lines(outputs, gen.CLAUDE_LOG)),
    ):
        seen = _three_state_counts(rows)
        assert seen["true"] >= 1, "{0}：缺 is_error=true 样本".format(label)
        assert seen["false"] >= 1, "{0}：缺 is_error=false 样本".format(label)
        assert seen["missing"] >= 1, "{0}：缺 is_error 字段缺失样本（M1 实测形态必须进基准）".format(label)


def test_log_three_state_counts_match_truth_declaration(outputs, truth):
    """日志里实际的三态计数必须与 truth.json 声明的逐 server 计数一致。

    这是比"各态 ≥1"强得多的性质：它让"把缺失态洗成 false"（或反之）任何一处
    篡改都会被抓出——只断言"≥1"时，4 条 unknown 洗掉 3 条仍会绿（变异验证实测）。
    """
    rows = _regenerated_lines(outputs, gen.CLAUDE_LOG)
    actual = {}
    call_server = {}
    for row in rows:
        if row.get("type") == "assistant":
            for block in (row.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block["name"]
                    call_server[block["id"]] = name.split("__")[1] if name.startswith("mcp__") else name
        elif row.get("type") == "user":
            for block in (row.get("message") or {}).get("content") or []:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                server = call_server.get(block["tool_use_id"], "?")
                bucket = actual.setdefault(server, {"ok": 0, "error": 0, "unknown": 0})
                if "is_error" not in block:
                    bucket["unknown"] += 1
                elif block["is_error"] is True:
                    bucket["error"] += 1
                else:
                    bucket["ok"] += 1

    for server in truth["claude"]["servers"]:
        name = server["server"]
        assert name in actual, "日志里没有 server {0}".format(name)
        assert actual[name] == {
            "ok": server["calls_ok"],
            "error": server["calls_error"],
            "unknown": server["calls_unknown"],
        }, "{0} 的三态计数与真值声明不符：实际 {1}".format(name, actual[name])


def test_some_unknown_sample_carries_error_text(outputs):
    """本机实测：缺失态中约 14.9% 含错误文本——基准必须覆盖该形态。"""
    for label, rows in (
        ("冻结产物", _read_claude_lines()),
        ("重生成", _regenerated_lines(outputs, gen.CLAUDE_LOG)),
    ):
        hits = 0
        for row in rows:
            if row.get("type") != "user":
                continue
            for block in (row.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_result" and "is_error" not in block:
                    if block.get("content") and block["content"] != "no status declared":
                        hits += 1
        assert hits >= 1, "{0}：缺【缺失态但含错误文本】的样本".format(label)


def test_claude_tool_use_and_tool_result_are_paired(outputs):
    for label, rows in (
        ("冻结产物", _read_claude_lines()),
        ("重生成", _regenerated_lines(outputs, gen.CLAUDE_LOG)),
    ):
        call_ids = set()
        result_ids = set()
        for row in rows:
            if row.get("type") == "assistant":
                for block in (row.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        call_ids.add(block["id"])
            elif row.get("type") == "user":
                for block in (row.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_ids.add(block["tool_use_id"])
        assert call_ids, "{0}：扫描面为空，断言可能空转".format(label)
        assert call_ids == result_ids, "{0}：tool_use 与 tool_result 未一一配对".format(label)


def test_every_claude_assistant_tool_use_carries_usage():
    """M1 实测：携带 tool_use 的 assistant 消息 100% 带 usage。"""
    count = 0
    for row in _read_claude_lines():
        if row.get("type") != "assistant":
            continue
        has_tool_use = any(
            isinstance(b, dict) and b.get("type") == "tool_use"
            for b in (row.get("message") or {}).get("content") or []
        )
        if has_tool_use:
            count += 1
            assert "usage" in row["message"], "tool_use 所在消息缺 usage"
    assert count >= 1, "扫描面为空"


def test_all_claude_server_names_are_fake_whitelist(outputs):
    for label, rows in (
        ("冻结产物", _read_claude_lines()),
        ("重生成", _regenerated_lines(outputs, gen.CLAUDE_LOG)),
    ):
        for row in rows:
            if row.get("type") != "assistant":
                continue
            for block in (row.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block["name"]
                    assert name.startswith("mcp__fake-"), "{0}：非白名单 server 名：{1}".format(label, name)


def test_claude_log_carries_version_detection_key():
    versions = set(row.get("version") for row in _read_claude_lines() if "version" in row)
    assert versions == {gen.CLAUDE_SOURCE_VERSION}, "version 检测键缺失或漂移：{0}".format(versions)


def test_codex_log_has_session_meta_version_and_no_mcp_prefix(outputs):
    for label, rows in (
        ("冻结产物", _read_codex_lines()),
        ("重生成", _regenerated_lines(outputs, gen.CODEX_LOG)),
    ):
        meta = [row for row in rows if row.get("type") == "session_meta"]
        assert len(meta) == 1, "{0}：session_meta 应恰 1 条".format(label)
        assert meta[0]["payload"]["cli_version"] == gen.CODEX_CLI_VERSION, label
        names = [
            row["payload"].get("name")
            for row in rows
            if row.get("type") == "response_item"
            and row["payload"].get("type") in ("function_call", "custom_tool_call")
        ]
        assert names, "{0}：扫描面为空".format(label)
        assert not any(str(name).startswith("mcp__") for name in names), "{0}：Codex 侧不应套用 Claude 前缀规则".format(label)


def test_codex_log_has_exit_code_text_and_an_unknown_sample():
    """Codex 成败只能靠 `Exit code:` 文本；无该文本者记 unknown。"""
    rows = _read_codex_lines()
    outputs = [
        str(row["payload"].get("output") or "")
        for row in rows
        if row.get("type") == "response_item"
        and row["payload"].get("type") in ("function_call_output", "custom_tool_call_output")
    ]
    assert outputs, "扫描面为空"
    assert any("Exit code: 0" in text for text in outputs), "缺成功样本"
    assert any("Exit code: 124" in text for text in outputs), "缺超时惯例值样本"
    assert any("Exit code:" not in text for text in outputs), "缺【无 Exit code】的 unknown 样本"


def test_codex_token_is_session_level_only():
    """K3：Codex token 只在 event_msg/token_count，不摊到单次工具调用。"""
    rows = _read_codex_lines()
    counters = [row for row in rows if row.get("type") == "event_msg" and row["payload"].get("type") == "token_count"]
    assert counters, "缺会话级 token 记录"
    for row in rows:
        if row.get("type") == "response_item":
            assert "usage" not in row["payload"], "Codex 单次调用不应带 token 归因"


# ---------------------------------------------------------------------------
# 边界与反向样例
# ---------------------------------------------------------------------------


def test_boundary_cases_present(truth):
    kinds = [case["kind"] for case in truth["boundary_cases"]]
    assert "threshold_exact" in kinds
    assert "near_miss" in kinds


def test_reverse_case_present(truth):
    assert truth["reverse_cases"], "缺反向样例（只测【该命中】会让阈值方向写反永远不红）"
    assert any(case["server"] == "fake-low-fail" for case in truth["reverse_cases"])


def test_threshold_exact_case_hits_and_near_miss_does_not(truth):
    """边界语义可证伪：exact 命中 remove_candidate，near_miss 不命中。"""
    by_server = dict((s["server"], s) for s in truth["claude"]["servers"])
    threshold = truth["rules_snapshot"]["remove_candidate"]["failure_rate_gte"]
    assert by_server["fake-threshold-exact"]["expected_failure_rate"] == threshold
    assert by_server["fake-threshold-exact"]["expected_suggestion"] == "remove_candidate"
    assert by_server["fake-near-miss"]["expected_failure_rate"] < threshold
    assert by_server["fake-near-miss"]["expected_suggestion"] != "remove_candidate"


def test_low_fail_server_is_not_a_remove_candidate(truth):
    by_server = dict((s["server"], s) for s in truth["claude"]["servers"])
    assert by_server["fake-low-fail"]["expected_suggestion"] != "remove_candidate"


def test_retry_server_declares_expected_retry_count(truth):
    by_server = dict((s["server"], s) for s in truth["claude"]["servers"])
    assert by_server["fake-retry"]["expected_retry_count"] >= 1


def test_spec_self_validation_rejects_inconsistent_specs(monkeypatch):
    """生成器自校验可证伪：规格改坏 → 必须报错而不是静默产出错真值。"""
    bad = [dict(spec) for spec in gen.SERVER_SPECS]
    bad[0]["calls"] = bad[0]["calls"] + 1
    monkeypatch.setattr(gen, "SERVER_SPECS", bad)
    with pytest.raises(SystemExit):
        gen._validate_specs()
