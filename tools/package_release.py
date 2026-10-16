#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发布源码包打包器（M6）：把 git 跟踪面打成确定性 zip（Release 附件）。

为什么用 `git ls-files` 而不是 `os.walk`：打包面 == 发布面由 git 背书，
未跟踪的本地杂项（venv / egg-info / 草稿）天然排除。

确定性（同一 dist → 同一 zip 字节）三件套：
  · ZIP_STORED（不压缩，避开压缩器实现差异）
  · 条目按路径排序（os.walk / ls-files 顺序跨调用不稳）
  · 全条目固定 date_time（取发布基准日）+ 固定外部属性 0644
注意：本工具承诺"打包这一步可复跑"（同源码树 → 同 zip 字节），
不承诺 zip 内文件内容跨环境一致（那由 .gitattributes eol=lf + 冻结守门负责）。

用法：py -X utf8 tools/package_release.py --out dist/mcp-tool-ops-lens-0.1.0-src.zip
"""
import argparse
import os
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "src"))

from opslens import _encoding  # noqa: E402

# 发布基准日（固定，非时钟读数——本工具不得读时钟）
FIXED_DATE = (2026, 10, 16, 0, 0, 0)
EXTERNAL_ATTR = 0o644 << 16


_SKIP_DIRS = (".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".egg-info", "dist", "build")


def _has_git():
    return os.path.isdir(os.path.join(_REPO, ".git"))


def _tracked_files(rev=None):
    """打包面清单：默认取工作树跟踪面；`rev` 给定则取该 rev 的树清单。

    用 `git ls-files` / `git ls-tree` 而非 `os.walk`：打包面 == 发布面由 git 背书，
    未跟踪的本地杂项（venv / egg-info / 草稿）天然排除。
    **无 git 兜底**：导出树（git archive / 源码 zip 解压）没有 `.git`，此时退回文件系统遍历
    （按特征剪掉 venv/缓存/构建目录，不按名字猜），使本工具在导出树里也能跑。
    """
    if _has_git():
        cmd = (["git", "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", rev] if rev
               else ["git", "-c", "core.quotepath=off", "ls-files"])
        proc = subprocess.run(cmd, cwd=_REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 0:
            names = [n for n in proc.stdout.decode("utf-8").splitlines() if n.strip()]
            if names:
                return sorted(names)
    names = []
    for dirpath, dirnames, filenames in os.walk(_REPO):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.endswith(".egg-info")]
        if "pyvenv.cfg" in filenames:
            continue
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            names.append(os.path.relpath(full, _REPO).replace(os.sep, "/"))
    return sorted(names)


def _file_bytes(name, rev=None):
    """取文件字节：`rev` 给定且**在 git 树内**则从该 rev 的 blob 读（保证附件与发布基线同字节）。"""
    if rev and _has_git():
        proc = subprocess.run(["git", "cat-file", "-p", "{0}:{1}".format(rev, name)],
                              cwd=_REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            raise SystemExit("[package] 读 {0}:{1} 失败".format(rev, name))
        return proc.stdout
    with open(os.path.join(_REPO, name.replace("/", os.sep)), "rb") as handle:
        return handle.read()


def _top_prefix(version):
    return "mcp-tool-ops-lens-{0}".format(version)


def build_zip(out_path, version, rev=None):
    names = _tracked_files(rev)
    assert len(names) >= 40, "打包面只有 {0} 个文件，疑似 git 清单空转".format(len(names))
    prefix = _top_prefix(version)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in names:
            info = zipfile.ZipInfo(filename=prefix + "/" + name, date_time=FIXED_DATE)
            info.external_attr = EXTERNAL_ATTR
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, _file_bytes(name, rev))
    return names


def main():
    _encoding.ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="发布源码包打包器（确定性 zip）")
    parser.add_argument("--out", required=True, help="输出 zip 路径")
    parser.add_argument("--version", default=None, help="版本号（缺省取 opslens.__version__）")
    parser.add_argument("--rev", default=None, help="从该 git rev 打包（缺省取工作树；发布时传 tag 保证与基线同字节）")
    args = parser.parse_args()

    version = args.version
    if version is None:
        import opslens
        version = opslens.__version__

    names = build_zip(args.out, version, rev=args.rev)
    import hashlib
    digest = hashlib.sha256(open(args.out, "rb").read()).hexdigest()
    print("[package] 打包 {0} 个文件（rev={1}）-> {2}".format(len(names), args.rev or "worktree", args.out))
    print("[package] sha256: {0}".format(digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
