#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M1 变异验证：每个新守门"故意弄坏 → 必红"。

纪律（HANDOFF-M1 §四 血泪）：
  · 替换前 assert marker 存在；替换后 assert 文件已变（防静默 no-op）。
  · 一律 try/finally 还原，还原后 assert 字节一致（防源码残留变异）。
  · marker 足够长以唯一定位代码行，不撞 docstring。

用法：py -X utf8 tools/mutation_check.py
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

    print("")
    print("变异验证结果：{0}/{1} 通过".format(sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
