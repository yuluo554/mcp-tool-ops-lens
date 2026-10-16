"""规则包门控测试：未核对规则不得进计算路径（plan/03 §3.2）。

变异验证：把 effective_patterns 的 status 门摘掉 → 本文件必红。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import config  # noqa: E402


def test_rules_pack_loads(rules_dir):
    rules = config.load_rules(rules_dir)
    assert rules.thresholds and rules.params and rules.patterns


def test_thresholds_are_not_hardcoded_elsewhere():
    """阈值只准来自规则包：包里有键，代码里不该有同样的数值。"""
    rules = config.load_rules()
    assert "failure_rate_gte" in rules.thresholds["remove_candidate"]
    assert "min_samples" in rules.thresholds


def test_ineffective_rules_are_excluded_from_effective_set():
    """pending 规则（content_refusal，本机 0 样例）不得生效。"""
    rules = config.load_rules()
    effective = rules.effective_patterns()
    ids = [r["id"] for r in effective]
    assert "F-REFUSE-1" not in ids, "未核对规则泄漏进计算路径"
    assert "F-TIMEOUT-1" in ids


def test_every_effective_rule_has_verified_samples():
    rules = config.load_rules()
    for rule in rules.effective_patterns():
        assert rule["status"] == config.STATUS_VERIFIED
        assert rule["verified_samples"], "{0} 缺已核对样例却生效".format(rule["id"])


def test_ineffective_rules_report_reasons():
    rules = config.load_rules()
    blocked = rules.ineffective_patterns()
    assert blocked, "本机实测存在 0 样例的规则，未生效清单不应为空"
    for item in blocked:
        assert item["reasons"], "未生效原因必须显式列出"


def test_missing_rules_dir_raises(rules_dir, tmp_home):
    import pytest

    with pytest.raises(config.ConfigError):
        config.load_rules(os.path.join(tmp_home, "nope"))


def test_default_rules_dir_points_at_repo_data(rules_dir):
    assert os.path.normcase(config.default_rules_dir()) == os.path.normcase(rules_dir)


def _write_pack(directory, rules):
    """造一份最小规则包，用于隔离测两条门。"""
    from opslens import serialize

    serialize.write_json(os.path.join(directory, "thresholds.json"), {"remove_candidate": {"failure_rate_gte": 0.5}})
    serialize.write_json(os.path.join(directory, "params.json"), {"retry": {"window_seconds": 120}})
    serialize.write_json(os.path.join(directory, "failure_patterns.json"), {"rules": rules})


def test_status_gate_is_independently_load_bearing(tmp_out):
    """只坏 status 门（samples 齐备）→ 该规则必须仍被拦住。

    verified_samples 非空，故唯一能拦住它的是 status 门。
    把 effective_patterns 里的 status 判断删掉 → 本测试必红（变异验证已实测）。
    """
    _write_pack(
        tmp_out,
        [
            {
                "id": "P-PENDING-WITH-SAMPLES",
                "category": "timeout",
                "status": "pending",
                "patterns": ["boom"],
                "verified_samples": ["有样例但状态仍是待核对"],
            }
        ],
    )
    rules = config.load_rules(tmp_out)
    assert rules.effective_patterns() == [], "status 门失效：待核对规则进了计算路径"


def test_samples_gate_is_independently_load_bearing(tmp_out):
    """只坏 samples 门（status 已是 verified）→ 该规则必须仍被拦住。"""
    _write_pack(
        tmp_out,
        [
            {
                "id": "P-VERIFIED-NO-SAMPLES",
                "category": "timeout",
                "status": "verified",
                "patterns": ["boom"],
                "verified_samples": [],
            }
        ],
    )
    rules = config.load_rules(tmp_out)
    assert rules.effective_patterns() == [], "samples 门失效：无已核对样例的规则进了计算路径"


def test_fully_qualified_rule_does_pass_both_gates(tmp_out):
    """阳性对照：两条门都满足时规则必须生效——否则上面两条"全拦住"是空转。"""
    _write_pack(
        tmp_out,
        [
            {
                "id": "P-OK",
                "category": "timeout",
                "status": "verified",
                "patterns": ["boom"],
                "verified_samples": ["真实样例"],
            }
        ],
    )
    rules = config.load_rules(tmp_out)
    assert [r["id"] for r in rules.effective_patterns()] == ["P-OK"]


# ---------------------------------------------------------------------------
# 合成覆盖度登记不得冒充"已核对样例"（防自证循环）
# ---------------------------------------------------------------------------


def test_synthetic_coverage_never_counts_as_verified_samples():
    """F-REFUSE-1 只有合成覆盖度、没有真实样例 → 必须仍不生效。"""
    rules = config.load_rules()
    by_id = dict((r["id"], r) for r in rules.patterns["rules"])

    refuse = by_id["F-REFUSE-1"]
    assert refuse["synthetic_coverage"]["claude_servers"], "该规则应登记合成覆盖度（基准会演练）"
    assert refuse["verified_samples"] == [], "合成植入不得被写成已核对样例"

    assert "F-REFUSE-1" not in [r["id"] for r in rules.effective_patterns()]


def test_synthetic_coverage_does_not_satisfy_the_samples_gate(tmp_out):
    """只挂 synthetic_coverage（无 verified_samples）的规则必须被 samples 门拦住。"""
    _write_pack(
        tmp_out,
        [
            {
                "id": "P-SYNTHETIC-ONLY",
                "category": "content_refusal",
                "status": "verified",
                "patterns": ["boom"],
                "verified_samples": [],
                "synthetic_coverage": {"claude_servers": ["fake-low-fail"]},
            }
        ],
    )
    rules = config.load_rules(tmp_out)
    assert rules.effective_patterns() == [], "合成覆盖度冒充了已核对样例"


def test_every_effective_rule_has_real_samples_not_synthetic_only():
    rules = config.load_rules()
    for rule in rules.effective_patterns():
        samples = rule.get("verified_samples") or []
        assert samples, "{0} 无真实样例却生效".format(rule["id"])
        for sample in samples:
            assert "synthetic" not in sample.lower(), "{0} 的样例疑似来自合成植入".format(rule["id"])
