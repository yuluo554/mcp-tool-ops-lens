"""纪律守门：零第三方依赖 / 零出网 / 无时钟无随机。

这些是"综合表现"栏（确定性纪律 + 隐私红线）的硬门，必须可证伪：
删除被测行为（如真的 import socket）→ 本文件必红。
"""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = (os.path.join(REPO_ROOT, "src"), os.path.join(REPO_ROOT, "tools"))

# 冻结的stdlib 名单（不用 sys.stdlib_module_names：3.10+ 才有，3.8 上是空集 → 全量假红）
STDLIB_FROZEN = frozenset(
    [
        "__future__",
        "argparse",
        "collections",
        "contextlib",
        "csv",
        "dataclasses",
        "datetime",
        "decimal",
        "errno",
        "functools",
        "glob",
        "html",
        "io",
        "itertools",
        "json",
        "math",
        "os",
        "pathlib",
        "re",
        "shutil",
        "sqlite3",
        "stat",
        "statistics",
        "string",
        "subprocess",
        "sys",
        "tempfile",
        "textwrap",
        "typing",
        "unicodedata",
        "unittest",
        "urllib",
        "warnings",
        "zipfile",
    ]
)

# 自家包（含测试注入形态）
OWN_PACKAGES = frozenset(["opslens", "conftest", "tests", "report_helpers"])

NETWORK_MODULES = frozenset(["socket", "http", "urllib", "requests", "ftplib", "smtplib", "ssl", "telnetlib"])
NONDETERMINISTIC_MODULES = frozenset(["random", "secrets", "uuid", "time"])


def _iter_py_files(dirs):
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        for dirpath, _dirnames, filenames in os.walk(directory):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(filenames):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def _toplevel_imports(path):
    """收集模块级与函数体内的全部 import 顶层名（AST 从严）。"""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_no_third_party_imports_in_source():
    """零第三方依赖：src/ 与 tools/ 只准 import 冻结 stdlib 名单或本包。"""
    offenders = {}
    for path in _iter_py_files(SCAN_DIRS):
        for name in _toplevel_imports(path):
            if name in STDLIB_FROZEN or name in OWN_PACKAGES:
                continue
            offenders.setdefault(os.path.relpath(path, REPO_ROOT), []).append(name)
    assert offenders == {}, "出现清单外的 import：{0}".format(offenders)


def test_no_network_modules_anywhere_in_source():
    """隐私红线：零出网。"""
    offenders = {}
    for path in _iter_py_files(SCAN_DIRS):
        hit = _toplevel_imports(path) & NETWORK_MODULES
        if hit:
            offenders[os.path.relpath(path, REPO_ROOT)] = sorted(hit)
    assert offenders == {}, "出现网络模块：{0}".format(offenders)


def test_no_clock_or_random_in_source():
    """确定性纪律：无时钟、无随机（合成生成器用自研 splitmix64）。"""
    offenders = {}
    for path in _iter_py_files(SCAN_DIRS):
        hit = _toplevel_imports(path) & NONDETERMINISTIC_MODULES
        if hit:
            offenders[os.path.relpath(path, REPO_ROOT)] = sorted(hit)
    assert offenders == {}, "出现非确定性模块：{0}".format(offenders)


def test_scan_dirs_are_not_empty():
    """扫描面非空自证：防"目录写错 → 一个文件都没扫 → 全部通过"的假绿。"""
    files = list(_iter_py_files(SCAN_DIRS))
    assert len(files) >= 5, "扫描面只有 {0} 个文件，守门可能空转".format(len(files))
