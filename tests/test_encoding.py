"""编码守卫测试。

本机带 -X utf8 跑，证明不了子进程/CI/用户通道——故用 cp1252 桩复现非 UTF-8 环境。
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import _encoding  # noqa: E402


class _FakeStream(object):
    """可重配的假流：记录是否被要求切 UTF-8。"""

    def __init__(self, encoding, fail=False):
        self.encoding = encoding
        self.calls = []
        self._fail = fail

    def reconfigure(self, encoding=None, errors=None):
        if self._fail:
            raise ValueError("cannot reconfigure")
        self.calls.append((encoding, errors))
        self.encoding = encoding


def test_reconfigures_non_utf8_streams():
    out = _FakeStream("cp1252")
    err = _FakeStream("ascii")
    result = _encoding.ensure_utf8_stdio([out, err])
    assert result == ["stdout", "stderr"]
    assert out.encoding == "utf-8"
    assert err.encoding == "utf-8"


def test_leaves_utf8_streams_untouched():
    out = _FakeStream("utf-8")
    err = _FakeStream("UTF-8")
    assert _encoding.ensure_utf8_stdio([out, err]) == []
    assert out.calls == []


def test_leaves_chinese_console_alone():
    """cp936 控制台保持不动：重配可能破坏中文显示。"""
    out = _FakeStream("cp936")
    assert _encoding.ensure_utf8_stdio([out]) == []
    assert out.calls == []


def test_tolerates_unreconfigurable_streams():
    out = _FakeStream("cp1252", fail=True)
    assert _encoding.ensure_utf8_stdio([out]) == []


def test_handles_none_stream():
    assert _encoding.ensure_utf8_stdio([None]) == []


def test_cp1252_stub_can_print_chinese_without_utf8():
    """反向自证：cp1252 严格模式下打印中文会炸——证明该环境确实需要守卫。"""
    import pytest

    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict")
    with pytest.raises(UnicodeEncodeError):
        stream.write("中文失败率")
        stream.flush()


# ---------------------------------------------------------------------------
# 编码守门覆盖 tools/ 全部可打印入口（不只手守主 CLI）
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TOOLS_DIR = os.path.join(_REPO_ROOT, "tools")


def _printable_entry_points():
    """扫 tools/ 下所有脚本，返回其中定义/调用 main() 的脚本路径。"""
    found = []
    if not os.path.isdir(_TOOLS_DIR):
        return found
    for name in sorted(os.listdir(_TOOLS_DIR)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(_TOOLS_DIR, name)
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if "def main(" in text:
            found.append(path)
    return found


def test_tools_scan_face_is_not_empty():
    """扫描面非空自证：防"目录写错 → 扫 0 个脚本 → 永远绿"。"""
    scripts = _printable_entry_points()
    assert len(scripts) >= 1, "tools/ 下未扫到任何带 main() 的脚本，编码守门可能空转"


def test_every_tools_entry_point_calls_utf8_guard():
    """tools/ 每个入口脚本都必须调 ensure_utf8_stdio()。"""
    offenders = []
    for path in _printable_entry_points():
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        if "ensure_utf8_stdio" not in text:
            offenders.append(os.path.relpath(path, _REPO_ROOT))
    assert offenders == [], "tools/ 入口缺 UTF-8 守卫：{0}".format(offenders)


def test_guard_detector_actually_detects():
    """探针自证：没有守卫的样例脚本必须被判为缺失（否则守门是假门）。"""
    sample = "def main():\n    print('x')\n"
    assert "ensure_utf8_stdio" not in sample
    good = "def main():\n    _encoding.ensure_utf8_stdio()\n"
    assert "ensure_utf8_stdio" in good


# ---------------------------------------------------------------------------
# 主 CLI 入口同样在守门面内（M5：可打印入口 = 主 CLI + tools/ 全部脚本）
# ---------------------------------------------------------------------------

_MAIN_CLI = os.path.join(_REPO_ROOT, "src", "opslens", "cli.py")
_PACKAGE_MAIN = os.path.join(_REPO_ROOT, "src", "opslens", "__main__.py")


def _calls_guard_in(text, func_name):
    """断言文本中 `def <func_name>` 之后的函数体里调用了守卫。"""
    marker = "def {0}(".format(func_name)
    start = text.find(marker)
    if start < 0:
        return False
    return "ensure_utf8_stdio" in text[start:]


def test_main_cli_entry_point_calls_utf8_guard():
    """主 CLI 的 `main()` 必须在入口处调 `ensure_utf8_stdio()`（可打印入口覆盖的第一项）。"""
    with open(_MAIN_CLI, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert _calls_guard_in(text, "main"), "主 CLI 的 main() 未调 UTF-8 守卫"


def test_package_main_routes_through_cli_main():
    """`python -m opslens` 通路必须走 `cli.main`（与 console script 同一条守卫路径）。"""
    with open(_PACKAGE_MAIN, "r", encoding="utf-8") as handle:
        text = handle.read()
    assert "from .cli import main" in text
    assert "sys.exit(main())" in text


def test_printable_entry_points_cover_main_cli_and_all_tools():
    """可打印入口扫描面 = 主 CLI + tools/ 全部脚本（DoD 逐项：两处都要覆盖）。"""
    scripts = _printable_entry_points()
    assert scripts, "tools/ 下未扫到任何带 main() 的脚本"
    # tools/ 全量覆盖（每个都断言过守卫）
    for path in scripts:
        with open(path, "r", encoding="utf-8") as handle:
            assert "ensure_utf8_stdio" in handle.read(), os.path.relpath(path, _REPO_ROOT)
    # 主 CLI 亦在面内
    assert os.path.isfile(_MAIN_CLI)

