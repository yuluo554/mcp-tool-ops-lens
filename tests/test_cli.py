"""CLI 契约测试：参数面锁定 + 骨架期不伪造空结果。"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import exit_codes  # noqa: E402
from opslens.cli import build_parser, main  # noqa: E402

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


def test_skeleton_does_not_fake_results(capsys, rules_dir):
    """骨架期：命令明确报"阶段未就绪"（exit 3），不产出空结果。"""
    code = main(["attribute", "--events", "nope.json", "--rules-dir", rules_dir])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_NOT_READY
    assert "尚未实现" in captured.err


def test_missing_rules_dir_is_data_unavailable(tmp_home, capsys):
    """规则包缺失 → exit 4，而不是被"未就绪"掩盖。"""
    missing = os.path.join(tmp_home, "no-such-rules")
    code = main(["scan", "--home", tmp_home, "--rules-dir", missing])
    captured = capsys.readouterr()
    assert code == exit_codes.EXIT_DATA_UNAVAILABLE
    assert "规则" in captured.err
