"""测试面 = 安装面 = README 指令面（skill 四面对账，本项目落两面）。

面①：README 里出现的 opslens 子命令 / 旗标，必须能在 CLI 里反射到。
面②：README 快速开始的安装行 extras，必须与 pyproject 声明一致。

变异验证：在 README 里写一个不存在的旗标 → 本文件必红。
"""

import ast
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens.cli import build_parser  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(REPO_ROOT, "README.md")
PYPROJECT = os.path.join(REPO_ROOT, "pyproject.toml")

COMMANDS = ("scan", "aggregate", "attribute", "report", "bench")


def _read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _cli_flags():
    """反射出每个子命令支持的旗标。"""
    parser = build_parser()
    flags = {}
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            for name, sub in action.choices.items():
                flags[name] = set()
                for sub_action in sub._actions:
                    flags[name].update(sub_action.option_strings)
    return flags


def test_readme_exists():
    assert os.path.isfile(README)


def test_every_command_documented_in_readme():
    text = _read(README)
    for name in COMMANDS:
        assert re.search(r"\bopslens\s+" + name + r"\b", text), "README 未记录命令 {0}".format(name)


def test_readme_flags_exist_in_cli():
    """READM 里形如 opslens <cmd> ... --flag 的旗标必须真实存在。"""
    text = _read(README)
    cli = _cli_flags()
    missing = []
    for match in re.finditer(r"opslens\s+(\w+)([^\n]*)", text):
        cmd, rest = match.group(1), match.group(2)
        if cmd not in cli:
            missing.append("未知子命令 {0}".format(cmd))
            continue
        for flag in re.findall(r"(--[a-z][a-z0-9-]*)", rest):
            if flag not in cli[cmd] and flag not in ("--help", "--version"):
                missing.append("{0} {1}".format(cmd, flag))
    assert missing == [], "README 出现不存在的命令/旗标：{0}".format(missing)


def test_readme_install_extras_match_pyproject():
    text = _read(README)
    declared = _extras_in_pyproject()
    used = set()
    for extras in re.findall(r'pip install -e "?\.\[([^\]]+)\]"?', text):
        for name in extras.split(","):
            used.add(name.strip())
    assert used, "README 未出现 pip install -e \".[...]\" 形式的安装行"
    undeclared = used - declared
    assert undeclared == set(), "README 引用了未声明的 extras：{0}".format(undeclared)


def _extras_in_pyproject():
    """pyproject.toml 不是 Python，按 TOML 节块正则取 extras 名。"""
    text = _read(PYPROJECT)
    block = re.search(r"\[project\.optional-dependencies\](.*?)(\n\[|\Z)", text, re.S)
    if not block:
        return set()
    return set(re.findall(r"^([A-Za-z0-9_.-]+)\s*=", block.group(1), re.M))


def test_pyproject_declares_zero_runtime_dependencies():
    text = _read(PYPROJECT)
    match = re.search(r"^dependencies\s*=\s*(\[.*?\])", text, re.M | re.S)
    assert match, "pyproject 未声明 dependencies"
    assert match.group(1).strip() == "[]", "运行时依赖必须为空（零第三方依赖）"


def test_console_script_entry_point_declared():
    text = _read(PYPROJECT)
    assert re.search(r'^opslens\s*=\s*"opslens\.cli:main"', text, re.M), "console script 未声明"


def test_src_layout_declared():
    text = _read(PYPROJECT)
    assert 'package-dir = { "" = "src" }' in text or 'package-dir = {"" = "src"}' in text
    assert 'where = ["src"]' in text
