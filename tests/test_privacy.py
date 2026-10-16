"""隐私红线守门（M1 实测：settings.json 的 env 含活体凭据）。

硬化口径：env 是"禁读键"——比"读了不打印"更强。本文件断言两条：
① 解析器源码不含读取 env 的取值路径；② 合成数据里出现假凭据值时，产物不得包含它。
"""

import ast
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本机真实 server 名：合成数据与仓内文件绝不允许出现（品牌/隐私隔离）
REAL_SERVER_NAMES = ("windows-mcp", "desktop-commander", "codegraph", "officecli", "installed_plugins")

# 本机实测含凭据的键名（只用于断言"未被读取"）
CREDENTIAL_KEY = "ANTHROPIC_AUTH_TOKEN"

# 允许出现这些词的文件（台账/计划文档说明实测结论时需要提及键名；
# 本测试文件自身是禁止词表的定义处，也必须豁免）
ALLOWED_MENTION_FILES = {
    os.path.join("plan", "01-题目文档.md"),
    os.path.join("plan", "02-架构与技术选型.md"),
    os.path.join("plan", "03-模块详设.md"),
    os.path.join("plan", "04-数据计划.md"),
    os.path.join("plan", "06-交付对标.md"),
    os.path.join("data", "README.md"),
    os.path.join("tests", "test_privacy.py"),
}

SOURCE_DIRS = (os.path.join(REPO_ROOT, "src"), os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests"))


def _iter_py(dirs):
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        for dirpath, _d, filenames in os.walk(directory):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(filenames):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def _string_key(node):
    """取子脚本的常量键值，兼容 3.8 的 ast.Index 包装与 3.9+ 的裸表达式。

    3.8 的 `a["env"]` 其 slice 是 Index(value=Constant)，3.9+ 才是 Constant——
    只认后者的写法在 3.8 上会静默漏判（变异验证实测抓出过一次假门）。
    """
    if isinstance(node, ast.Index):  # Python 3.8
        node = node.value
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def test_source_never_reads_the_env_block():
    """源码不得出现以 "env" 为键的取值（防整体 json.load 后取 env）。"""
    offenders = []
    for path in _iter_py(SOURCE_DIRS):
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                if _string_key(node.slice) == "env":
                    offenders.append("{0}:{1}".format(os.path.relpath(path, REPO_ROOT), node.lineno))
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "get":
                    if node.args and _string_key(node.args[0]) == "env":
                        offenders.append("{0}:{1}".format(os.path.relpath(path, REPO_ROOT), node.lineno))
    assert offenders == [], "出现读取 env 的路径：{0}".format(offenders)


def test_env_detector_actually_detects():
    """探针自证：给出含 env 取值的样例源码，检测逻辑必须命中两种写法。

    防"探针自己坏了 → 全扫描永远绿"（面3 教训：抽取到空集也是红不了的原因之一）。
    """
    samples = ['x = settings["env"]\n', 'x = settings.get("env")\n']
    for sample in samples:
        tree = ast.parse(sample)
        hit = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and _string_key(node.slice) == "env":
                hit = True
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                if node.args and _string_key(node.args[0]) == "env":
                    hit = True
        assert hit, "探针漏判了样例：{0!r}".format(sample)


def test_no_credential_constant_appears_in_source():
    offenders = []
    for path in _iter_py(SOURCE_DIRS):
        with open(path, "r", encoding="utf-8") as handle:
            if CREDENTIAL_KEY in handle.read():
                offenders.append(os.path.relpath(path, REPO_ROOT))
    # 本测试自身必须提及该键名以完成断言，故只允许 tests/ 下本文件
    allowed = os.path.join("tests", "test_privacy.py")
    offenders = [p for p in offenders if p != allowed]
    assert offenders == [], "凭据键名出现在源码：{0}".format(offenders)


def test_real_server_names_absent_from_repo_content():
    """真实 server 名不得进入仓内文件（合成数据用 fake-* 白名单）。"""
    offenders = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", ".venv", ".pytest_cache")]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, REPO_ROOT)
            if rel in ALLOWED_MENTION_FILES:
                continue
            if any(part in rel for part in (".egg-info",)):
                continue
            try:
                with open(full, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except (UnicodeDecodeError, OSError):
                continue
            for real in REAL_SERVER_NAMES:
                if real in text:
                    offenders.append("{0} <- {1}".format(rel, real))
    assert offenders == [], "真实 server 名泄漏：{0}".format(offenders)
