"""退出码语义锁进测试（plan/02 §六）。

M2 起退出码 `3`（阶段未就绪）已**整项退役**：本文件用 `not hasattr` 断言防其复活
（幽灵语义复活 = 有人把"未实现"重新当成一种"正常结果"）。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import exit_codes  # noqa: E402


def test_exit_code_values_are_frozen():
    assert exit_codes.EXIT_OK == 0
    assert exit_codes.EXIT_FINDINGS == 1
    assert exit_codes.EXIT_USAGE == 2
    assert exit_codes.EXIT_DATA_UNAVAILABLE == 4


def test_retired_not_ready_code_is_gone():
    """退役型语义：常量必须已删除（防幽灵语义复活）。

    这里断言的是**不存在**。若有人把 `EXIT_NOT_READY` 加回来，本断言立刻变红。
    """
    assert not hasattr(exit_codes, "EXIT_NOT_READY"), (
        "退出码 3 已随 M2 退役：不得复活该常量（骨架期占位语义没有第二次生命）"
    )


def test_domain_errors_carry_their_exit_codes():
    assert exit_codes.UsageError("x").exit_code == 2
    assert exit_codes.DataUnavailableError("x").exit_code == 4
    assert exit_codes.SchemaVersionError("x").exit_code == 4


def test_schema_version_error_is_a_data_unavailable_error():
    """版本不识别属"数据不可用"，故必须是其子类（否则调用方的 except 会漏接）。"""
    assert issubclass(exit_codes.SchemaVersionError, exit_codes.DataUnavailableError)


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
