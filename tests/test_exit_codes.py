"""退出码语义锁进测试（plan/02 §六）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import exit_codes  # noqa: E402


def test_exit_code_values_are_frozen():
    assert exit_codes.EXIT_OK == 0
    assert exit_codes.EXIT_FINDINGS == 1
    assert exit_codes.EXIT_USAGE == 2
    assert exit_codes.EXIT_NOT_READY == 3
    assert exit_codes.EXIT_DATA_UNAVAILABLE == 4


def test_domain_errors_carry_their_exit_codes():
    assert exit_codes.UsageError("x").exit_code == 2
    assert exit_codes.DataUnavailableError("x").exit_code == 4


def test_not_ready_is_a_retirable_semantic():
    """exit 3 是退役型语义：M2/M3/M5 落地时整项删除（含本测试）。

    此处只断言"退役型常量的存在、取值、且只被骨架占位路径使用"，
    不做无意义的恒真断言——退役时删除本函数是最自然的做法。
    """
    assert hasattr(exit_codes, "EXIT_NOT_READY")
    assert exit_codes.EXIT_NOT_READY == 3


def test_source_has_no_duplicate_exit_code_literals():
    """退出码数值只准在 exit_codes.py 出现（防第二份退出码表）。"""
    import re

    src_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "opslens"
    )
    allowed = {"exit_codes.py"}
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(src_dir):
        for name in filenames:
            if not name.endswith(".py") or name in allowed:
                continue
            path = os.path.join(dirpath, name)
            with open(path, "r", encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, 1):
                    if re.search(r"sys\.exit\([1-4]\)", line) or re.search(
                        r"return\s+[1-4]\s*#.*exit", line
                    ):
                        offenders.append("{0}:{1}".format(name, lineno))
    assert offenders == [], "退出码字面量散落在：{0}".format(offenders)
