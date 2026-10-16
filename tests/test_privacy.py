"""隐私红线守门（M1 实测：settings.json 的 env 含活体凭据）。

硬化口径：env 是"禁读键"——比"读了不打印"更强。本文件断言两条：
① 解析器源码不含读取 env 的取值路径；② 合成数据里出现假凭据值时，产物不得包含它。
"""

import ast
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本机真实 server 名（plan/04 §二）：合成数据与仓内文件绝不允许出现（品牌/隐私隔离）。
# 分两类：① 辨识度高的名字按裸子串匹配；② 与常用英文词同形的名字
# （fetch / memory / time）只在 `mcp__<name>__` 命名空间形态下匹配——
# 否则 `\btime\b` 会命中 "Wall time:"、`timeout` 等正常文本，产生假红。
REAL_SERVER_NAMES = ("windows-mcp", "desktop-commander", "codegraph", "officecli", "installed_plugins")
REAL_SERVER_NAME_TOKENS = ("fetch", "memory", "time")


def _real_server_hits(text):
    """返回文本中命中的真实 server 名（两类匹配规则合一）。"""
    hits = [name for name in REAL_SERVER_NAMES if name in text]
    for token in REAL_SERVER_NAME_TOKENS:
        if re.search(r"mcp__" + re.escape(token) + r"__", text):
            hits.append("mcp__{0}__".format(token))
    return hits


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
    scanned = 0
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
            scanned += 1
            for hit in _real_server_hits(text):
                offenders.append("{0} <- {1}".format(rel, hit))
    assert scanned >= 20, "扫描面只有 {0} 个文件，守门可能空转".format(scanned)
    assert offenders == [], "真实 server 名泄漏：{0}".format(offenders)


def test_forbidden_word_detector_actually_detects():
    """探针自证：两类匹配都必须命中样例，否则守门是假门。"""
    assert _real_server_hits("mcp__windows-mcp__PowerShell") == ["windows-mcp"]
    assert "mcp__time__" in _real_server_hits("tool name mcp__time__get_current_time")
    # 反向自证：正常文本里的 time 不误伤（否则假红会让守门被关掉）
    assert _real_server_hits("Wall time: 0.5 seconds / Exit code: 124") == []


# ---------------------------------------------------------------------------
# M6 脱敏审计器随全量测试常驻（并入本文件，函数个数不变 → 收集数不变）
# ---------------------------------------------------------------------------

def _audit_module():
    import importlib.util
    path = os.path.join(REPO_ROOT, "tools", "audit_desensitize.py")
    spec = importlib.util.spec_from_file_location("opslens_audit_desensitize", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_desensitize_auditor_selftest_and_tracked_scan_are_clean():
    """脱敏审计器（M6 固化形态）的机制自证 + 跟踪面扫描必须全过。

    并入本测试函数（非新增函数）以保持收集数不变；覆盖：
    ① 阳性对照（四类模式必须命中）与阴性对照（noreply/传输地址不误报）；
    ② 跟踪文件名 + 文本内容 + 二进制样例三层扫描 0 硬门命中，且扫描面非空。
    历史层（第 4 步）不在此断言——CI 检出为浅克隆，历史扫描在彼处天然不完整，
    由 tools/audit_desensitize.py 全量模式在完整 clone 下跑。
    """
    module = _audit_module()
    module.selftest()  # 阳性/阴性对照（坏了会 AssertionError）
    text_scanned, tracked_total, hits, _source = module._scan_tracked_text()
    assert tracked_total >= 40, "扫描面过小（{0}），审计器可能空转".format(tracked_total)
    assert text_scanned >= 40, "文本扫描面过小（{0}）".format(text_scanned)
    _bin_scanned, bin_hits = module._scan_binary()
    assert hits == [] and bin_hits == [], "脱敏审计硬门命中：{0}".format(hits + bin_hits)

    # ③ CI 的 checkout 必须取全量历史（fetch-depth: 0）——否则审计器第 4 步在 CI 里
    #    静默削弱成空验（浅克隆只见 1 提交）。守门打在 workflow 文本上，防"CI 也跑了历史扫描"是假的。
    workflow = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
    with open(workflow, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    checkout_lines = [i for i, ln in enumerate(lines) if "actions/checkout@" in ln]
    assert checkout_lines, "ci.yml 未找到 checkout 步骤（扫描面为空）"
    step_starts = [i for i, ln in enumerate(lines) if ln.startswith("      - ")]
    for i in checkout_lines:
        end = min([s for s in step_starts if s > i] or [len(lines)])
        window = "\n".join(lines[i:end])
        assert "fetch-depth: 0" in window, (
            "ci.yml 的 checkout 未配 fetch-depth: 0（浅克隆会让脱敏审计的历史扫描空验）"
        )

    # ④ 无 git 兜底：导出树（git archive / 源码 zip 解压）没有 `.git`，审计器必须退回
    #    文件系统遍历而**不崩**——本项目 M6 发布物自检实录：首版硬依赖 `git ls-files`，
    #    在解压出来的源码 zip 里直接 SystemExit（发布物本体复核当场抓出）。
    #    断言方式：把 _REPO 指到一个无 .git 的临时树，走 _tracked_names() 必须返回非空清单。
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "pkg"))
        with open(os.path.join(tmp, "pkg", "a.py"), "w", encoding="utf-8") as handle:
            handle.write("x = 1\n")
        os.makedirs(os.path.join(tmp, ".venv"))
        with open(os.path.join(tmp, ".venv", "pyvenv.cfg"), "w", encoding="utf-8") as handle:
            handle.write("home = x\n")
        saved = module._REPO
        try:
            module._REPO = tmp
            names, source = module._tracked_names()
        finally:
            module._REPO = saved
        assert "pkg/a.py" in names, "无 .git 兜底未扫到普通文件：{0}".format(names)
        assert not any(n.startswith(".venv/") for n in names), "无 .git 兜底未剪掉 venv"
        assert source != "git ls-files", "无 .git 树不应走 git 通路"

    # ⑤ 发布打包器（tools/package_release.py）必须可跑且确定性：
    #    改 `--rev` 时曾因漏掉 `_top_prefix` 定义直接 NameError（发布期实测抓出）——
    #    守门按"两跑同字节"打在打包器上，防"发布工具本身坏了"。
    pkg = os.path.join(REPO_ROOT, "tools", "package_release.py")
    assert os.path.isfile(pkg)
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out1 = os.path.join(tmp, "a.zip")
        out2 = os.path.join(tmp, "b.zip")
        env = dict(os.environ, PYTHONUTF8="1")
        for out in (out1, out2):
            proc = subprocess.run([sys.executable, "-X", "utf8", pkg, "--out", out],
                                  cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert proc.returncode == 0, "打包器退出 {0}：{1}".format(
                proc.returncode, proc.stdout.decode("utf-8", "replace")[-500:])
        with open(out1, "rb") as h1, open(out2, "rb") as h2:
            assert h1.read() == h2.read(), "打包器两跑字节不一致（确定性被破坏）"
