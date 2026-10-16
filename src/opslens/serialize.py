"""确定性写盘唯一入口（plan/02 §四）。

全项目所有产物写盘必须经此模块，禁止各子命令各写各的 open()+json.dump()。
冻结契约（K）：json.dumps(sort_keys=True, ensure_ascii=False, indent=2)
    + UTF-8 无 BOM + LF 换行 + 结尾换行 + 原子 rename。
"""

import json
import os
import tempfile

ENCODING = "utf-8"


def dumps(obj):
    """对象 -> 确定性 JSON 文本（含结尾换行、LF 行尾）。"""
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2)
    return text + "\n"


def write_atomic(path, text):
    """原子写：先写同目录临时文件再 os.replace，防中断留下半个产物。

    行尾一律 LF（不经文本模式的 newline 翻译），字节与平台无关。
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    fd, tmp = tempfile.mkstemp(prefix=".opslens-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode(ENCODING))
        os.replace(tmp, path)
    except BaseException:
        _quiet_remove(tmp)
        raise
    return path


def dumps_compact(obj):
    """紧凑确定性 JSON（单行、无缩进）——供 JSONL 行使用。

    JSONL 的每一行必须是单行 JSON，故不能复用带 indent 的 dumps()；
    但排序/转义口径与 dumps() 一致（sort_keys + ensure_ascii=False）。
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def write_json(path, obj):
    """确定性 JSON 写盘。"""
    return write_atomic(path, dumps(obj))


def write_jsonl(path, rows):
    """确定性 JSONL 写盘：每行一个紧凑 JSON，LF 行尾，结尾 LF，原子替换。"""
    text = "".join(dumps_compact(row) + "\n" for row in rows)
    return write_atomic(path, text)


def read_json(path):
    with open(path, "r", encoding=ENCODING) as handle:
        return json.load(handle)


def read_text(path):
    with open(path, "r", encoding=ENCODING) as handle:
        return handle.read()


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
