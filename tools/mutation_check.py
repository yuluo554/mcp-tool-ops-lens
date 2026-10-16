#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁变异验证：每个新守门"故意弄坏 → 必红"。

纪律（HANDOFF-M1 §四 血泪）：
  · 替换前 assert marker 存在；替换后 assert 文件已变（防静默 no-op）。
  · 一律 try/finally 还原，还原后 assert 字节一致（防源码残留变异）。
  · marker 足够长以唯一定位代码行，不撞 docstring。

M1 十项 + M2 六项 + M3 六项。用法：py -X utf8 tools/mutation_check.py
"""

import io
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "src"))
from opslens import _encoding  # noqa: E402

PY = sys.executable


def _read(path):
    with io.open(path, "rb") as handle:
        return handle.read()


def _write(path, raw):
    with io.open(path, "wb") as handle:
        handle.write(raw)


def _run_tests(targets):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    proc = subprocess.run(
        [PY, "-X", "utf8", "-m", "pytest", "-q"] + list(targets),
        cwd=_REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _mutate(path, marker, replacement, targets, label):
    original = _read(path)
    text = original.decode("utf-8")
    assert marker in text, "[{0}] marker 不存在，变异会静默 no-op：{1!r}".format(label, marker[:60])
    mutated = text.replace(marker, replacement, 1)
    assert mutated != text, "[{0}] 替换后文件未变".format(label)
    try:
        _write(path, mutated.encode("utf-8"))
        assert _read(path) != original, "[{0}] 写盘未生效".format(label)
        code, out = _run_tests(targets)
        return code, out
    finally:
        _write(path, original)
        assert _read(path) == original, "[{0}] 还原后字节不一致".format(label)


def _report(label, code, out, expect_red=True):
    red = code != 0
    status = "PASS" if red == expect_red else "FAIL"
    tail = [line for line in out.strip().splitlines() if line.strip()][-1:] or [""]
    print("  [{0}] {1} -> exit={2} ({3})".format(status, label, code, tail[0][:90]))
    return status == "PASS"


def main():
    _encoding.ensure_utf8_stdio()
    results = []
    gen = os.path.join(_REPO, "tools", "gen_synthetic_logs.py")
    truth = os.path.join(_REPO, "data", "synthetic", "truth.json")
    manifest = os.path.join(_REPO, "data", "synthetic", "manifest.json")
    rules = os.path.join(_REPO, "data", "rules", "failure_patterns.json")

    print("M1 变异验证（每项：故意弄坏 → 对应测试必红）")

    # 1. --check 位级守门：把比对逻辑改成恒等（永远一致）
    code, out = _mutate(
        gen,
        "        if on_disk != text.encode(\"utf-8\"):\n            mismatches.append(\"{0}: 与重生成结果不一致\".format(relative))",
        "        if False:\n            mismatches.append(\"{0}: 与重生成结果不一致\".format(relative))",
        ["tests/test_synthetic_data.py::test_regeneration_is_byte_identical_to_frozen_artifacts",
         "tests/test_synthetic_data.py::test_check_detects_mismatch"],
        "check 位级比对恒真",
    )
    results.append(_report("check 位级比对恒真", code, out))

    # 2. RNG 确定性：换掉 splitmix64 的增量常数 → 双跑不一致
    code, out = _mutate(
        gen,
        "_GOLDEN_GAMMA = 0x9E3779B97F4A7C15",
        "_GOLDEN_GAMMA = 0x9E3779B97F4A7C16",
        ["tests/test_synthetic_data.py::test_regeneration_is_byte_identical_to_frozen_artifacts"],
        "RNG 常数漂移",
    )
    results.append(_report("RNG 常数漂移", code, out))

    # 3. 真值库观测字段守门：把 expected_failure_rate 改成 observed_failure_rate
    code, out = _mutate(
        truth,
        "\"expected_failure_rate\"",
        "\"observed_failure_rate\"",
        ["tests/test_synthetic_data.py::test_truth_has_no_observed_fields"],
        "真值库注入观测字段",
    )
    results.append(_report("真值库注入观测字段", code, out))

    # 4. 覆盖度双登记守门：把采样数改成 0
    code, out = _mutate(
        manifest,
        "\"sampled_forms\": 4",
        "\"sampled_forms\": 0",
        ["tests/test_synthetic_data.py::test_manifest_coverage_double_registers_totals_and_samples"],
        "manifest 采样数清零",
    )
    results.append(_report("manifest 采样数清零", code, out))

    # 5. tools/ 编码守门：摘掉生成器入口的 UTF-8 守卫
    code, out = _mutate(
        gen,
        "    _encoding.ensure_utf8_stdio()\n    args = build_parser().parse_args(argv)",
        "    args = build_parser().parse_args(argv)",
        ["tests/test_encoding.py::test_every_tools_entry_point_calls_utf8_guard"],
        "tools/ 入口摘掉编码守卫",
    )
    results.append(_report("tools/ 入口摘掉编码守卫", code, out))

    # 6. 合成覆盖度冒充已核对样例：给 F-REFUSE-1 塞入合成来源的 verified_samples
    code, out = _mutate(
        rules,
        "\"verified_samples\": [],",
        "\"verified_samples\": [\"synthetic implanted refusal text\"],",
        ["tests/test_rules_gate.py::test_synthetic_coverage_never_counts_as_verified_samples",
         "tests/test_rules_gate.py::test_every_effective_rule_has_real_samples_not_synthetic_only"],
        "合成植入冒充已核对样例",
    )
    results.append(_report("合成植入冒充已核对样例", code, out))

    # 7. 三态守门：把缺失样本写成 is_error=false（把 unknown 洗成成功）
    code, out = _mutate(
        gen,
        "                seen = unknown_seen.get(server, 0)",
        "                result[\"is_error\"] = False\n                seen = unknown_seen.get(server, 0)",
        ["tests/test_synthetic_data.py::test_claude_log_contains_all_three_states",
         "tests/test_synthetic_data.py::test_log_three_state_counts_match_truth_declaration"],
        "unknown 被洗成 ok",
    )
    results.append(_report("unknown 被洗成 ok", code, out))

    # 8. 隐私禁止词表：把真实 server 名塞进一个仓内文件
    # 名字用拼接构造：本脚本自身也是扫描面，写死字面量会被自家守门判为泄漏。
    real_name = "windows" + "-" + "mcp"
    victim = os.path.join(_REPO, "tools", "_mutation_probe.txt")
    try:
        _write(victim, ("mcp__{0}__PowerShell\n".format(real_name)).encode("utf-8"))
        code, out = _run_tests(["tests/test_privacy.py::test_real_server_names_absent_from_repo_content"])
        results.append(_report("真实 server 名入仓", code, out))
    finally:
        if os.path.exists(victim):
            os.remove(victim)
        assert not os.path.exists(victim), "变异探针文件未清理"

    # 9. 生成器自校验守门：把规格改成 calls != ok+error+unknown
    code, out = _mutate(
        gen,
        "        if spec[\"ok\"] + spec[\"error\"] + spec[\"unknown\"] != spec[\"calls\"]:",
        "        if False:",
        ["tests/test_synthetic_data.py::test_spec_self_validation_rejects_inconsistent_specs"],
        "规格自校验恒假",
    )
    results.append(_report("规格自校验恒假", code, out))

    # 10. 覆盖度登记可验证性：把 F-REFUSE-1 指向一个没有该类失败文本的 server
    code, out = _mutate(
        rules,
        "\"claude_servers\": [\"fake-low-fail\"],",
        "\"claude_servers\": [\"fake-high-fail\"],",
        ["tests/test_synthetic_data.py::test_synthetic_error_texts_match_their_declared_rule_patterns"],
        "覆盖度登记指向无该类失败的 server",
    )
    results.append(_report("覆盖度登记指向无该类失败的 server", code, out))

    # =======================================================================
    # M2 变异项：解析层守门
    # =======================================================================
    parsers = os.path.join(_REPO, "src", "opslens", "parsers")
    versions_py = os.path.join(parsers, "versions.py")
    claude_py = os.path.join(parsers, "claude_jsonl.py")
    codex_py = os.path.join(parsers, "codex_rollout.py")
    config_py = os.path.join(parsers, "claude_config.py")

    # 11. 版本检测"万能匹配"：把不在集合内的判断改成恒假（永远放行）
    code, out = _mutate(
        versions_py,
        "    if version not in SUPPORTED_CLAUDE_VERSIONS:",
        "    if False:",
        ["tests/test_parsers.py::test_unknown_claude_version_raises_data_unavailable",
         "tests/test_parsers.py::test_version_check_is_exact_membership_not_pattern_match"],
        "Claude 版本集合改万能匹配",
    )
    results.append(_report("Claude 版本集合改万能匹配", code, out))

    # 12. Codex 版本检测同样改万能匹配
    code, out = _mutate(
        versions_py,
        "    if cli_version not in SUPPORTED_CODEX_CLI_VERSIONS:",
        "    if False:",
        ["tests/test_parsers.py::test_unknown_codex_cli_version_raises_data_unavailable"],
        "Codex 版本集合改万能匹配",
    )
    results.append(_report("Codex 版本集合改万能匹配", code, out))

    # 13. 三态：把缺失 is_error 洗成 ok（本题正确性核心的变异）
    code, out = _mutate(
        claude_py,
        "        notes.append(\"status_undeclared\")\n        return schema.STATUS_UNKNOWN, common.text_of_content(block.get(\"content\"))",
        "        notes.append(\"status_undeclared\")\n        return schema.STATUS_OK, common.text_of_content(block.get(\"content\"))",
        ["tests/test_parsers.py::test_unknown_is_not_silently_promoted_to_ok",
         "tests/test_parsers.py::test_claude_three_state_counts_reconcile_with_truth"],
        "缺失 is_error 被洗成 ok",
    )
    results.append(_report("缺失 is_error 被洗成 ok", code, out))

    # 14. Codex：把"无 Exit code 文本"当成 ok（哑值当判据的同族错误）
    code, out = _mutate(
        codex_py,
        "            if exit_code is None:\n                status = schema.STATUS_UNKNOWN",
        "            if exit_code is None:\n                status = schema.STATUS_OK",
        ["tests/test_parsers.py::test_codex_three_state_counts_reconcile_with_truth",
         "tests/test_parsers.py::test_codex_missing_exit_code_text_is_unknown"],
        "Codex 无退出码文本被洗成 ok",
    )
    results.append(_report("Codex 无退出码文本被洗成 ok", code, out))

    # 15. env 禁读：把禁读键搬进输出结构（隐私红线变异）
    # 注意：只改 `picked = dict(raw)` 是**假变异**——输出结构是按显式键重建的，
    # 整体透传并不泄漏 env（本项首版就是这么写的，跑出 exit=0 才发现）。
    # 真实故障形态是"有人往输出结构里加了一个 env 字段"，故按该形态变异。
    code, out = _mutate(
        config_py,
        "        \"enabled_plugins\": _plugin_names(picked.get(\"enabledPlugins\")),\n    }",
        "        \"enabled_plugins\": _plugin_names(picked.get(\"enabledPlugins\")),\n        \"env\": raw.get(\"env\"),\n    }",
        ["tests/test_parsers.py::test_env_credential_never_reaches_output",
         "tests/test_parsers.py::test_env_credential_absent_from_end_to_end_events"],
        "env 进产物结构（隐私红线）",
    )
    results.append(_report("env 进产物结构（隐私红线）", code, out))

    # 16. seq 退化成数组下标（K11 最硬形态的变异）
    code, out = _mutate(
        claude_py,
        "                        \"line\": line_no,\n                        \"seq\": line_no,",
        "                        \"line\": line_no,\n                        \"seq\": len(calls),",
        ["tests/test_parsers.py::test_claude_seq_is_source_line_number_not_array_index",
         "tests/test_parsers.py::test_seq_is_not_the_compacted_index"],
        "seq 退化成数组下标",
    )
    results.append(_report("seq 退化成数组下标", code, out))

    # =======================================================================
    # M3 变异项：聚合层与归因层守门
    # =======================================================================
    aggregate_py = os.path.join(_REPO, "src", "opslens", "aggregate.py")
    attribute_py = os.path.join(_REPO, "src", "opslens", "attribute.py")
    common_py = os.path.join(parsers, "common.py")
    cli_py = os.path.join(_REPO, "src", "opslens", "cli.py")

    # 17. 失败率分母口径：把 unknown 计入分母（K1 核心的变异）
    code, out = _mutate(
        aggregate_py,
        "    denominator = calls_ok + calls_error  # unknown 不进分母（K1）",
        "    denominator = calls_ok + calls_error + calls_unknown",
        ["tests/test_aggregate.py::test_failure_rate_denominator_excludes_unknown",
         "tests/test_aggregate.py::test_failure_rate_matches_truth_per_server",
         "tests/test_aggregate.py::test_failure_rate_would_differ_if_unknown_were_counted"],
        "unknown 计入失败率分母",
    )
    results.append(_report("unknown 计入失败率分母", code, out))

    # 18. 对账等式守门：把断言改成恒假（三态之和 != 总数 时不再报错）
    code, out = _mutate(
        aggregate_py,
        "    if calls_ok + calls_error + calls_unknown != calls_total:",
        "    if False:",
        ["tests/test_aggregate.py::test_accounting_identity_breaks_are_detected"],
        "对账等式守门恒假",
    )
    results.append(_report("对账等式守门恒假", code, out))

    # 19. 口径唯一性守门：把除法挪进 CLI 层（第二份比率计算的真实故障形态）
    code, out = _mutate(
        cli_py,
        "def _default_home():\n    return os.path.expanduser(\"~\")",
        "def _default_home():\n    rate = 1 / 2\n    return os.path.expanduser(\"~\")",
        ["tests/test_aggregate.py::test_binop_div_only_in_aggregate_and_attribute_and_generator"],
        "除法挪进 CLI 层（口径唯一性）",
    )
    results.append(_report("除法挪进 CLI 层（口径唯一性）", code, out))

    # 20. 规则门控：摘掉 status 门（未生效规则进计算路径）
    config_py = os.path.join(_REPO, "src", "opslens", "config.py")
    code, out = _mutate(
        config_py,
        "            if rule.get(\"status\") != STATUS_VERIFIED:\n                continue",
        "            if False:\n                continue",
        ["tests/test_rules_gate.py::test_status_gate_is_independently_load_bearing",
         "tests/test_attribute.py::test_pending_rule_does_not_enter_computation_path",
         "tests/test_rules_gate.py::test_ineffective_rules_are_excluded_from_effective_set"],
        "规则 status 门被摘掉（未生效规则进计算路径）",
    )
    results.append(_report("规则 status 门被摘掉（未生效规则进计算路径）", code, out))

    # 21. 规则门控：摘掉 verified_samples 门（无样例规则进计算路径）
    code, out = _mutate(
        config_py,
        "            if not rule.get(\"verified_samples\"):\n                continue",
        "            if False:\n                continue",
        ["tests/test_rules_gate.py::test_samples_gate_is_independently_load_bearing",
         "tests/test_rules_gate.py::test_synthetic_coverage_does_not_satisfy_the_samples_gate"],
        "规则 samples 门被摘掉（无样例规则进计算路径）",
    )
    results.append(_report("规则 samples 门被摘掉（无样例规则进计算路径）", code, out))

    # 22. 归因匹配面：把匹配面从 error_text 放宽到全部事件（成功记录误命中宽模式）
    code, out = _mutate(
        attribute_py,
        "        if event.status != schema.STATUS_ERROR:",
        "        if False:",
        ["tests/test_attribute.py::test_only_error_events_participate",
         "tests/test_attribute.py::test_success_records_are_not_matched",
         "tests/test_attribute.py::test_unknown_with_error_text_is_not_attributed"],
        "归因匹配面放宽到成功/unknown 记录",
    )
    results.append(_report("归因匹配面放宽到成功/unknown 记录", code, out))

    # 23. 错误文本归一回归：退回"只留首行"（多行失败签名被丢弃）
    code, out = _mutate(
        common_py,
        "    normalized = _WHITESPACE_RUN.sub(\" \", (text or \"\")).strip()",
        "    normalized = (text or \"\").split(\"\\n\", 1)[0].strip()",
        ["tests/test_parsers.py::test_error_text_is_whitespace_normalized_not_first_line_only",
         "tests/test_attribute.py::test_timeout_rule_actually_matches_multiline_error_text"],
        "错误文本退回首行截断（丢多行失败签名）",
    )
    results.append(_report("错误文本退回首行截断（丢多行失败签名）", code, out))

    # 24. 重试口径：把窗口判断改成"永远在窗口内"（保留 `?` 绑定，故是真实的口径失效）
    code, out = _mutate(
        aggregate_py,
        "            AND (ts_seconds - LAG(ts_seconds) OVER w) <= ?",
        "            AND (ts_seconds - LAG(ts_seconds) OVER w) <= ? * 1000000",
        ["tests/test_aggregate.py::test_retry_count_matches_truth_per_server",
         "tests/test_aggregate.py::test_retry_window_change_changes_the_count"],
        "重试窗口判断恒真（窗口参数失效）",
    )
    results.append(_report("重试窗口判断恒真（窗口参数失效）", code, out))

    # =======================================================================
    # M4 变异项：真值基准（模块 5）守门
    # =======================================================================
    bench_py = os.path.join(_REPO, "src", "opslens", "bench.py")

    # 25. 探活机制：把探活结果恒判为"已检出"（假门——弄坏了也不报）
    code, out = _mutate(
        bench_py,
        "    detected = len(probe_outcome[\"diffs\"]) > 0",
        "    detected = True",
        ["tests/test_bench.py::test_all_probes_turn_red",
         "tests/test_bench.py::test_probe_is_load_bearing_for_every_suite",
         "tests/test_bench.py::test_probe_verdict_is_derived_from_rerunning_the_check"],
        "探活结果恒判已检出（探活是假门）",
    )
    results.append(_report("探活结果恒判已检出（探活是假门）", code, out))

    # 26. 未启用分支：把 not_enabled 恒判为 False（"未启用"冒充通过）
    code, out = _mutate(
        bench_py,
        "        result[\"status\"] = STATUS_NOT_ENABLED\n        result[\"not_enabled\"] = True",
        "        result[\"status\"] = STATUS_PASS\n        result[\"not_enabled\"] = False",
        ["tests/test_bench.py::test_not_enabled_when_no_effective_rules",
         "tests/test_bench.py::test_not_enabled_suite_is_not_counted_as_passed"],
        "未启用套件冒充通过（空分母分支失效）",
    )
    results.append(_report("未启用套件冒充通过（空分母分支失效）", code, out))

    # 27. 对账等式：把三态对账的比较改成恒真（引擎输出与真值不再真正比对）
    code, out = _mutate(
        bench_py,
        "        for field in (\"calls_total\", \"calls_ok\", \"calls_error\", \"calls_unknown\"):\n            if row[field] != declared[field]:",
        "        for field in (\"calls_total\", \"calls_ok\", \"calls_error\", \"calls_unknown\"):\n            if False:",
        ["tests/test_bench.py::test_diffs_are_listed_item_by_item",
         "tests/test_bench.py::test_probe_detector_actually_detects"],
        "三态对账比较恒真（对账失效）",
    )
    results.append(_report("三态对账比较恒真（对账失效）", code, out))

    # 28. `--only` 白名单：把未知名改成静默跑全部（未知名不再报用法错误）
    code, out = _mutate(
        bench_py,
        "        suite = suite_by_id(only)\n        if suite is None:",
        "        suite = suite_by_id(only)\n        if False:",
        ["tests/test_bench.py::test_unknown_only_is_usage_error",
         "tests/test_bench.py::test_unknown_only_via_cli_is_exit_2"],
        "--only 未知名被静默放行（白名单失效）",
    )
    results.append(_report("--only 未知名被静默放行（白名单失效）", code, out))

    # 29. 覆盖声明：把"非穷举"声明的检查摘掉（覆盖声明不再消费 manifest）
    code, out = _mutate(
        bench_py,
        "    if \"非穷举\" not in declaration:",
        "    if False:",
        ["tests/test_bench.py::test_coverage_declaration_consumes_manifest",
         "tests/test_bench.py::test_coverage_suite_flags_missing_non_exhaustive_declaration"],
        "覆盖声明的非穷举检查被摘掉",
    )
    results.append(_report("覆盖声明的非穷举检查被摘掉", code, out))

    # 30. 解析基线：把 F1 判定改成恒通过（基线假绿）
    code, out = _mutate(
        bench_py,
        "    if f1 != 1.0:",
        "    if False:",
        ["tests/test_bench.py::test_parse_baseline_f1_drops_when_engine_is_wrong",
         "tests/test_bench.py::test_parse_baseline_reports_no_diff_when_f1_is_one"],
        "解析基线 F1 判定恒通过（基线假绿）",
    )
    results.append(_report("解析基线 F1 判定恒通过（基线假绿）", code, out))

    print("")
    print("变异验证结果：{0}/{1} 通过".format(sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
