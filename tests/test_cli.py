"""CLI 契约测试：参数面锁定 + 未落地命令不伪造结果 + scan 通路。"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import exit_codes  # noqa: E402
from opslens.cli import IMPLEMENTED_COMMANDS, build_parser, main  # noqa: E402

EXPECTED_COMMANDS = ("scan", "aggregate", "attribute", "report", "bench")


def _subparsers(parser):
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            return action.choices
    return {}


def test_all_five_module_commands_registered():
    subs = _subparsers(build_parser())
    for name in EXPECTED_COMMANDS:
        assert name in subs, "缺少子命令 {0}".format(name)


def test_every_command_has_help_text():
    subs = _subparsers(build_parser())
    for name in EXPECTED_COMMANDS:
        assert subs[name].description or subs[name].format_help().strip()


def test_implemented_commands_track_the_built_modules():
    """已落地子命令清单 = 当前已接通的模块面（M5：五模块闭环齐备）。"""
    assert IMPLEMENTED_COMMANDS == ("scan", "aggregate", "attribute", "report", "bench")
    # 注册的子命令与已落地清单**逐一对应**（防"没做却被登记成已做"或反之）
    assert set(IMPLEMENTED_COMMANDS) == set(_subparsers(build_parser()))


def test_scan_accepts_home_flag():
    """--home 是显式传参通路：测试与演示都靠它避免误扫真实用户目录。"""
    parser = build_parser()
    args = parser.parse_args(["scan", "--home", "/tmp/nowhere"])
    assert args.home == "/tmp/nowhere"
    assert args.command == "scan"


def test_bench_accepts_only_and_check():
    parser = build_parser()
    args = parser.parse_args(["bench", "--only", "B1", "--check"])
    assert args.only == "B1"
    assert args.check is True


def test_report_requires_out():
    parser = build_parser()
    try:
        parser.parse_args(["report", "--events", "e.json"])
    except SystemExit as exc:
        assert exc.code == exit_codes.EXIT_USAGE
    else:
        raise AssertionError("report 缺 --out 必须报用法错误")


def test_unknown_command_is_usage_error():
    parser = build_parser()
    try:
        parser.parse_args(["nope"])
    except SystemExit as exc:
        assert exc.code == exit_codes.EXIT_USAGE
    else:
        raise AssertionError("未知名必须报用法错误")


def test_no_command_prints_help_and_returns_usage_code(capsys):
    code = main([])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_USAGE
    assert "usage" in captured.out.lower() or "用法" in captured.out


def test_unimplemented_command_does_not_fake_results(capsys, rules_dir):
    """未落地命令：明确报"本构建尚未包含"，**绝不产出空结果**。

    骨架期这里给的是退出码 3（阶段未就绪）；该语义已随 M2 退役，
    现按"该命令在本构建里不可用"= 用法错误（2）处理。

    M5 起五个子命令**全部落地**，故已无"未落地子命令"可作探针——
    本测试改为**直接打那个兜底函数**（`_not_in_this_build`），
    保住"绝不伪造空结果"这条纪律：任何将来新增但未接通的子命令都会走它。
    """
    from opslens.cli import _not_in_this_build

    code = _not_in_this_build("future-command")
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_USAGE
    assert "尚未包含" in captured.err
    assert "future-command" in captured.err


def test_no_registered_command_falls_through_to_the_fallback(rules_dir):
    """兜底路径不得被已注册命令走到：五个子命令都必须有自己的 handler。"""
    subs = set(_subparsers(build_parser()))
    assert subs == set(IMPLEMENTED_COMMANDS)
    # 每个已落地命令都必须能真正跑通（而非落到"尚未包含"）——用 report 缺文件验一条
    code = main(["report", "--events", "definitely-missing.json", "--out", "out", "--rules-dir", rules_dir])
    assert code == exit_codes.EXIT_DATA_UNAVAILABLE, "report 落到了兜底/未落地路径"


def test_missing_rules_dir_is_data_unavailable(tmp_home, capsys):
    """规则包缺失 → exit 4，而不是被"未实现"掩盖。"""
    missing = os.path.join(tmp_home, "no-such-rules")
    code = main(["scan", "--home", tmp_home, "--rules-dir", missing])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_DATA_UNAVAILABLE
    assert "规则" in captured.err


def test_scan_on_empty_home_is_data_unavailable(tmp_home, rules_dir, capsys):
    """空数据源 → exit 4（不是 0，也不是静默空报告）。"""
    code = main(["scan", "--home", tmp_home, "--rules-dir", rules_dir])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_DATA_UNAVAILABLE
    assert "没有可解析" in captured.err


def test_scan_writes_events_and_reports_counts(synthetic_home, rules_dir, tmp_out, capsys):
    out = os.path.join(tmp_out, "events.json")
    code = main(["scan", "--home", synthetic_home, "--out", out, "--rules-dir", rules_dir])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_OK
    assert os.path.isfile(out)
    assert "解析完成" in captured.out

    with open(out, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["schema"] == "opslens.events/1"
    assert payload["count"] == len(payload["events"])
    assert payload["count"] > 0
    # 三态在产物里可见（"未声明"不得看起来像"没问题"）
    statuses = set(item["status"] for item in payload["events"])
    assert statuses == {"ok", "error", "unknown"}


def test_scan_without_out_still_succeeds(synthetic_home, rules_dir, capsys):
    code = main(["scan", "--home", synthetic_home, "--rules-dir", rules_dir])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_OK
    assert "解析完成" in captured.out


def test_scan_unknown_version_reports_exit_4(tmp_home, rules_dir, capsys):
    """喂未知版本号 → exit 4 + 报错含检测键路径（可演示物）。"""
    directory = os.path.join(tmp_home, ".claude", "projects", "p")
    os.makedirs(directory)
    with open(os.path.join(directory, "s.jsonl"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"type": "system", "version": "9.9.999", "session_id": "s"}) + "\n")
    code = main(["scan", "--home", tmp_home, "--rules-dir", rules_dir])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_DATA_UNAVAILABLE
    assert "9.9.999" in captured.err
    assert "version" in captured.err
