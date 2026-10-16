#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""脱敏审计器（M6 固化形态）：四步 + 产物扫描，任一步 FAIL 非零退出。

四步（skill 阶段 7）：
  1. 跟踪文件名扫描（.env / .key / secret / token）
  2. 跟踪文本文件内容扫描（密钥 / 邮箱 / 手机号 / 身份证 / 内网 IP / 个人路径）
  3. 二进制样例字节扫描（ASCII 与 UTF-16LE 两种编码各编一遍；本项目暂无入仓二进制）
  4. 全历史 blob 扫描 + 提交元数据邮箱（逐 commit 迭代，不用 `git grep` 多 rev 陷阱）

纪律：
  · 判据按字面量，且 ASCII / UTF-16LE 各扫一遍（宽字符每字符夹 NUL；"去 NUL 再匹配"会拼出假阳性）。
  · 输出一律掩码化，不回显敏感串原文——审计报告本身不得成为二次泄漏源。
  · 个人标记按"组合路径签名"匹配（`Users<名>`），不匹配裸用户名（防厂商串如 ASUSTek 误报）。
  · 模式文本用**片段拼接**构造，防审计器源码被自身扫描判红。
  · 机制探活：每次运行先对阳性对照命中，否则报"扫描器坏了"。
  · 浅克隆（CI 检出形态）下历史扫描只见 1 个提交 → 显式报出，不静默空扫。

用法：py -X utf8 tools/audit_desensitize.py [--tracked-only] [--selftest]
退出码：0 全过（打印 DESSENSITIZE_AUDIT_OK）/ 1 有硬门命中 / 2 环境不支持该模式
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_REPO, "src"))

from opslens import _encoding  # noqa: E402

# ---------------------------------------------------------------------------
# 模式表（片段拼接构造，避免源码里出现完整敏感词面而被自身扫描命中）
# ---------------------------------------------------------------------------
_DASH = "-"
_AT = "@"
_SEP = chr(92)  # 反斜杠，运行时构造防转义地狱
_SEP_RE = re.escape(_SEP)  # 正则里 `\U` 是非法转义，须转义后再拼

TEXT_PATTERNS = {
    "sk_key": re.compile("sk" + _DASH + "[A-Za-z0-9]{10,}"),
    "email": re.compile("[A-Za-z0-9._%+" + _DASH + "]+" + _AT + "[A-Za-z0-9." + _DASH + "]+[.][A-Za-z]{2,}"),
    "phone_cn": re.compile("(?<![0-9a-fA-F])1[3-9][0-9]{9}(?![0-9a-fA-F])"),
    "idcard": re.compile("(?<![0-9a-fA-F])[0-9]{17}[0-9Xx](?![0-9a-fA-F])"),
    "internal_ip": re.compile(r"\b(?:10[.]\d{1,3}|192[.]168|172[.](?:1[6-9]|2\d|3[01]))[.]\d{1,3}[.]\d{1,3}\b"),
    "personal_path_win": re.compile("[A-Za-z]:" + _SEP_RE + "Users" + _SEP_RE),
    "other_drive_abs": re.compile("[A-Za-z]:" + _SEP_RE + "(?:ProgramData|program|Program|workspace)" + _SEP_RE),
}

# 发布固有公开元数据（非个人邮箱）：noreply 是脱敏目标形态；git/ssh/hg 传输地址
_EMAIL_ALLOW = re.compile("(" + _AT + "users[.]noreply[.]github[.]com$)|(^(?:git|ssh|hg)" + _AT + "[A-Za-z0-9." + _DASH + "]+$)")

# 文件名硬门（第 1 步）
_FILENAME_HARD = re.compile(r"(\.env$|\.key$|secret|token)", re.I)


def _git(*args):
    proc = subprocess.run(["git", "-c", "core.quotepath=off"] + list(args),
                          cwd=_REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _mask(value):
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _personal_markers():
    """本机个人标记：用户目录组合签名 + 工作根签名（运行时实算，不写死字面量）。"""
    markers = []
    home = os.path.expanduser("~")
    user = os.path.basename(home.rstrip(_SEP + "/")) if home else ""
    if user:
        markers.append(("personal_user_dir", "Users" + _SEP + user))
    # 工作根签名：仓库绝对路径的父目录名（仓库目录名本身是有意公开的项目坐标，不收）
    repo_parent = os.path.basename(os.path.dirname(_REPO))
    if repo_parent:
        markers.append(("work_root", repo_parent + _SEP + os.path.basename(_REPO)))
    return markers


_SKIP_DIRS = (".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".egg-info", "dist", "build")


def _is_tracked_tree():
    """是否处于 git 工作树（有 `.git`）。"""
    return os.path.isdir(os.path.join(_REPO, ".git"))


def _tracked_names():
    """跟踪面清单；**无 git 兜底**：导出树（git archive / 源码 zip 解压）无 `.git`，
    此时退回文件系统遍历（按特征剪掉 venv/缓存/构建目录，不按名字猜）。

    释放树是"证明跟踪树本身可跑通"的常用形态（skill 阶段 7），
    而依赖 git 的扫描器若不做兜底，在无 `.git` 树里会直接崩——本项目 M6 发布物自检实录。
    """
    if _is_tracked_tree():
        rc, listing = _git("ls-files")
        if rc == 0:
            names = [f for f in listing.splitlines() if f.strip()]
            if names:
                return names, "git ls-files"
    names = []
    for dirpath, dirnames, filenames in os.walk(_REPO):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.endswith(".egg-info")]
        if "pyvenv.cfg" in filenames:
            continue  # 就地建的 venv 不算跟踪树
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, _REPO).replace(os.sep, "/")
            names.append(rel)
    return sorted(names), "filesystem walk (无 .git 兜底)"


def _scan_tracked_text():
    files, source = _tracked_names()
    hits = []
    scanned = 0
    for name in files:
        if _FILENAME_HARD.search(os.path.basename(name)):
            hits.append(("step1_filename", name, "文件名命中 .env/.key/secret/token"))
        path = os.path.join(_REPO, name.replace("/", os.sep))
        try:
            raw = open(path, "rb").read()
        except OSError:
            continue
        if b"\x00" in raw:
            continue  # 二进制走第 3 步
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for pname, pattern in TEXT_PATTERNS.items():
            for match in pattern.finditer(text):
                value = match.group(0)
                if pname == "email" and _EMAIL_ALLOW.search(value):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                hits.append(("step2_content", "{0}:{1}".format(name, line), "{0} {1}".format(pname, _mask(value))))
    return scanned, len(files), hits, source


def _scan_binary():
    files, _source = _tracked_names()
    markers = _personal_markers()
    hits = []
    scanned = 0
    for name in files:
        path = os.path.join(_REPO, name.replace("/", os.sep))
        try:
            raw = open(path, "rb").read()
        except OSError:
            continue
        if b"\x00" not in raw:
            continue
        scanned += 1
        for mname, literal in markers:
            for enc in ("ascii", "utf-16-le"):
                try:
                    needle = literal.encode(enc)
                except UnicodeEncodeError:
                    continue
                if needle in raw:
                    hits.append(("step3_binary", name, "{0} ({1})".format(mname, enc)))
    return scanned, hits


def _scan_history():
    if not _is_tracked_tree():
        # 无 .git（导出树 / 源码 zip 解压）：历史面**根本不存在**——显式报出，
        # 不静默当作"历史干净"（"我没扫到东西"要大声说）。
        return None, [], "无 .git（导出树，历史扫描不适用）"
    rc, revs_out = _git("rev-list", "--all")
    revs = [r for r in revs_out.splitlines() if r.strip()]
    if not revs:
        return 0, [], "无提交"
    if len(revs) == 1:
        # 浅克隆（CI 检出形态）：只见到 1 个提交 → 全历史扫描**无法成立**，
        # 显式报出并让调用方按 exit 2 退出（"我没扫到东西"要大声说，不静默空扫）。
        return len(revs), [], "浅克隆（只见 1 提交）"
    hits = []
    for rev in revs:
        rc2, listing = _git("ls-tree", "-r", "--name-only", rev)
        for name in listing.splitlines():
            if not name.strip():
                continue
            blob = subprocess.run(["git", "cat-file", "-p", "{0}:{1}".format(rev, name)],
                                  cwd=_REPO, stdout=subprocess.PIPE).stdout
            if b"\x00" in blob:
                continue
            try:
                text = blob.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for pname, pattern in TEXT_PATTERNS.items():
                for match in pattern.finditer(text):
                    value = match.group(0)
                    if pname == "email" and _EMAIL_ALLOW.search(value):
                        continue
                    hits.append(("step4_history", "{0} {1}".format(rev[:8], name), "{0} {1}".format(pname, _mask(value))))
    return len(revs), hits, ""


def _scan_commit_metadata():
    rc, out = _git("log", "--all", "--format=%ae%n%ce%n%s%n%b")
    hits = []
    emails = set()
    for token in out.splitlines():
        if _AT in token:
            emails.add(token)
    for email in sorted(emails):
        if _EMAIL_ALLOW.search(email):
            continue
        hits.append(("commit_email", email, "非 noreply 邮箱"))
    # 提交信息正文扫内容模式
    for pname, pattern in TEXT_PATTERNS.items():
        for match in pattern.finditer(out):
            if pname == "email" and _EMAIL_ALLOW.search(match.group(0)):
                continue
            hits.append(("commit_message", pname, _mask(match.group(0))))
    return sorted(emails), hits


def selftest():
    """阳性对照 + 阴性对照：扫描机制必须真能命中，且公开元数据不误报。

    合成串一律**运行时拼接构造**——审计器源码自己也在扫描面内，写死字面量会被自身判红。
    """
    fake_phone = "138" + "0013" + "8000"
    fake_key = "sk" + _DASH + "ABCDEFGHIJ" + "123456"
    fake_mail = "a" + _AT + "b.com"
    positive = "path C:" + _SEP + "Users" + _SEP + "alice mail " + fake_mail + " " + fake_key + " phone " + fake_phone
    for pname in ("sk_key", "email", "phone_cn", "personal_path_win"):
        assert TEXT_PATTERNS[pname].search(positive), "阳性对照未命中 {0} → 扫描器坏了".format(pname)
    # 阴性对照：noreply / 传输地址不得当个人邮箱
    for safe in ("282769740+yuluo554" + _AT + "users.noreply.github.com", "git" + _AT + "github.com"):
        assert _EMAIL_ALLOW.search(safe), "阴性对照被误报：{0}".format(safe)
    # 阳性对照：非 noreply 必须被判为命中
    assert not _EMAIL_ALLOW.search("someone" + _AT + "example.org"), "真邮箱被误豁免"
    print("[audit] selftest: OK（阳性对照命中四类；noreply/传输地址正确豁免）")


def main():
    _encoding.ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="脱敏审计器（四步 + 产物扫描）")
    parser.add_argument("--tracked-only", action="store_true", help="只跑第 1–3 步（跳过历史，CI 浅克隆下可用）")
    parser.add_argument("--selftest", action="store_true", help="只跑机制自证（阳性/阴性对照）")
    args = parser.parse_args()

    selftest()
    if args.selftest:
        print("DESSENSITIZE_AUDIT_OK")
        return 0

    print("[audit] 仓库：{0}".format(os.path.basename(_REPO)))
    text_scanned, tracked_total, hits, source = _scan_tracked_text()
    print("[audit] 扫描面来源：{0}".format(source))
    print("[audit] 第1步 跟踪文件名扫描：{0} 个文件".format(tracked_total))
    assert tracked_total >= 40, "扫描面过小（{0}），疑似空转".format(tracked_total)
    print("[audit] 第2步 文本内容扫描：{0} 个文本文件".format(text_scanned))
    assert text_scanned >= 40, "文本扫描面过小（{0}）".format(text_scanned)

    bin_scanned, bin_hits = _scan_binary()
    print("[audit] 第3步 二进制样例扫描：{0} 个二进制文件".format(bin_scanned))
    hits.extend(bin_hits)

    if args.tracked_only:
        revs, hist_hits, note = None, [], "skipped (--tracked-only)"
        emails, meta_hits = [], []
    else:
        revs, hist_hits, note = _scan_history()
        hits.extend(hist_hits)
        emails, meta_hits = _scan_commit_metadata()
        hits.extend(meta_hits)
        if revs == 1:
            print("[audit] 第4步 全历史扫描：浅克隆（只见 1 提交）——历史面无法成立")
            print("[audit] 结论：INCOMPLETE（浅克隆下全历史扫描为空，需 fetch-depth: 0）")
            return 2
        if revs is None:
            # 无 .git：历史面不适用，但跟踪面（1–3 步）已扫过——如实声明，不冒充"历史已验"
            print("[audit] 第4步 全历史扫描：不适用（{0}）".format(note))

    for step, where, what in hits:
        print("  [HIT] {0} {1} <- {2}".format(step, where, what))
    print("[audit] 提交元数据邮箱：{0}".format(
        ", ".join(_mask(e) for e in emails) if emails else "(未扫)"))
    if revs is not None:
        print("[audit] 第4步 全历史扫描：{0} 个提交{1}".format(revs, ("（" + note + "）") if note else ""))
    if hits:
        print("[audit] 结论：FAIL（{0} 处硬门命中）".format(len(hits)))
        return 1
    print("[audit] 结论：PASS（0 硬门命中）")
    print("DESSENSITIZE_AUDIT_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
