"""安装面契约守门：wheel 不带规则包 → 干净安装后 `bench` **必须** 退出码 4。

本仓的发布口径是"源码包 + editable 安装"（README 已知环境问题节），wheel 形态**不承诺**
开箱可跑：规则包 `data/rules/*.json` 在包外（`pyproject.toml` 无 `package-data`），
所以安装态 `bench` 以退出码 4 报「规则目录不存在」，需显式 `--rules-dir`。

这段行为在 README 里已被写死为契约，故用测试**钉住两侧**：

- 前件：wheel 里确实没有 rules/data 条目（否则下面的"缺规则"根本没有原因）。
- 契约：全新 venv 装该 wheel → `bench` 退出码 **4** 且 stderr 含「规则目录不存在」。
  它**不得悄悄变成 0**（有人偷偷加了 package-data 却没同步 README/契约），
  也**不得悄悄能跑**（同上）——两种漂移都会让本文件变红。
- 探活（可证伪自证）：同一个 venv 显式传 `--rules-dir` / `--data-dir` → `bench` 退出码 **0**。
  这一条证明"上面的 4"是**缺规则目录**导致的，而不是安装本身坏了（假门会让这一条也红）。

变异验证：给 `pyproject.toml` 加 `[tool.setuptools] package-data`（或 `include-package-data=true`
并把 data 搬进 `src/opslens/`）→ 前件与契约同时变红。删掉 `--rules-dir` 传递 →
探活变红（若引擎其实坏掉，探活先红，契约那条就不可信了）。
"""

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(REPO_ROOT, "data", "rules")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")

# 子进程环境：UTF-8 固定，否则 Windows 下中文消息会按 GBK 落地、replacement 掉断言子串。
CHILD_ENV = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")

# 构建输入剪枝：.venv/build/dist/update 都不是 wheel 的输入，复制它们只会拖慢并引入陈旧态。
COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "__pycache__", "build", "dist", "*.egg-info", ".pytest_cache", "update",
)


def _run(argv, cwd=None, timeout=600):
    proc = subprocess.run(
        argv, cwd=cwd, env=CHILD_ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _build_wheel(source_dir, out_dir):
    """用当前解释器的 pip 建 wheel；优先免隔离（离线可跑），失败再退回默认隔离。"""
    base = [sys.executable, "-m", "pip", "wheel", source_dir, "--no-deps", "-w", out_dir,
            "--disable-pip-version-check", "--no-cache-dir"]
    attempts = []
    for extra in (["--no-build-isolation"], []):
        code, out = _run(base + extra)
        attempts.append((code, out, extra))
        built = glob.glob(os.path.join(out_dir, "*.whl"))
        if code == 0 and built:
            return built[0]
    trail = "\n".join("退出码 {0} · 参数 {1}\n{2}".format(c, e, o[-800:]) for c, o, e in attempts)
    raise AssertionError("wheel 构建失败（两种构建模式都不可用）：\n" + trail)


def _make_venv(target):
    code, out = _run([sys.executable, "-m", "venv", target])
    assert code == 0, "venv 创建失败（退出码 {0}）：\n{1}".format(code, out[-800:])
    scripts = "Scripts" if os.name == "nt" else "bin"
    python = os.path.join(target, scripts, "python.exe" if os.name == "nt" else "python")
    assert os.path.isfile(python), "venv 里找不到解释器：{0}".format(python)
    return python


def test_wheel_install_contract_rules_dir_missing():
    """主契约。单个 fixture 走完整链路：建 wheel → 建 venv → 装 → 中立目录跑 bench。"""
    workdir = tempfile.mkdtemp(prefix="opslens-install-")
    try:
        source = os.path.join(workdir, "src-tree")
        shutil.copytree(REPO_ROOT, source, ignore=COPY_IGNORE)

        wheels_dir = os.path.join(workdir, "wheels")
        os.makedirs(wheels_dir)
        wheel_path = _build_wheel(source, wheels_dir)

        # 前件：wheel 本身不带规则包（契约成立的原因），且 license 元数据已落盘（批次 1 的可观测面）。
        with zipfile.ZipFile(wheel_path) as archive:
            names = archive.namelist()
        leaked = [n for n in names if n.startswith("data/") or "/data/rules/" in n or n.endswith("rules.json")]
        assert leaked == [], "wheel 里出现了规则包条目：{0}（契约前件被破坏，需同步 README/契约）".format(leaked)
        assert any("dist-info/licenses/LICENSE" in n for n in names), \
            "wheel 缺 licenses/LICENSE（license-files 未生效）：{0}".format(names)

        venv_dir = os.path.join(workdir, "venv")
        venv_python = _make_venv(venv_dir)

        code, out = _run([venv_python, "-m", "pip", "install", wheel_path,
                          "--no-index", "--no-deps", "--disable-pip-version-check"])
        assert code == 0, "wheel 安装失败（退出码 {0}）：\n{1}".format(code, out[-1200:])

        scripts = "Scripts" if os.name == "nt" else "bin"
        opslens = os.path.join(venv_dir, scripts, "opslens.exe" if os.name == "nt" else "opslens")
        assert os.path.isfile(opslens), "安装后找不到 console script：{0}".format(opslens)

        # 契约：中立目录（非仓库根）跑 bench → 4 + 明确的"缺规则目录"消息。
        neutral = os.path.join(workdir, "neutral")
        os.makedirs(neutral)
        code, out = _run([opslens, "bench"], cwd=neutral)
        assert code == 4, "wheel 安装态 bench 期望退出码 4（缺规则目录），实得 {0}：\n{1}".format(code, out[-1200:])
        assert "规则目录不存在" in out, "退出码对了但消息不含「规则目录不存在」：\n{0}".format(out[-1200:])

        # 探活：同一 venv 补上规则/数据 → 0。证明上面的 4 是"缺目录"而非"装坏了"。
        code, out = _run([opslens, "bench", "--rules-dir", RULES_DIR, "--data-dir", SYNTHETIC_DIR],
                         cwd=neutral)
        assert code == 0, "同一 venv 显式传 --rules-dir/--data-dir 后 bench 应退出 0，实得 {0}：\n{1}".format(
            code, out[-1200:])
        assert "基准达标" in out, "bench 退出 0 但未见达标汇总行：\n{0}".format(out[-800:])
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
