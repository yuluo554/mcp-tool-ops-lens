"""共享测试夹具。

隐私纪律：夹具一律造临时目录并显式传参，绝不回落到自动发现（防误扫真实用户会话）。
"""

import os
import shutil
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
RULES_DIR = os.path.join(REPO_ROOT, "data", "rules")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


@pytest.fixture
def tmp_home():
    """空的临时 home：显式传给被测代码，防"缺省参数有副作用"类误扫。"""
    path = tempfile.mkdtemp(prefix="opslens-home-")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def tmp_out():
    path = tempfile.mkdtemp(prefix="opslens-out-")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def rules_dir():
    return RULES_DIR


@pytest.fixture
def run_cli():
    """以进程内方式跑 CLI，返回 (exit_code, stdout, stderr)。"""
    from opslens.cli import main

    def _run(argv, capsys=None):
        try:
            code = main(argv)
        except SystemExit as exc:  # argparse 的 version/error 通路
            code = exc.code if isinstance(exc.code, int) else 1
        out = err = ""
        if capsys is not None:
            captured = capsys.readouterr()  # 只能消费一次
            out, err = captured.out, captured.err
        return code, out, err

    return _run
