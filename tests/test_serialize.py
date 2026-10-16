"""确定性写盘守门（skill：序列化参数冻结 + 双跑逐字节一致）。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import serialize  # noqa: E402


def test_dumps_sorts_keys_and_keeps_unicode():
    text = serialize.dumps({"b": 1, "a": "中文"})
    assert text.startswith("{\n  \"a\"")  # keys 已排序
    assert "中文" in text  # ensure_ascii=False
    assert "\\u4e2d" not in text


def test_dumps_ends_with_single_lf_and_no_crlf():
    text = serialize.dumps({"a": 1})
    assert text.endswith("}\n")
    assert "\r" not in text


def test_write_atomic_is_byte_identical_across_runs(tmp_out):
    payload = {"x": [1, 2, 3], "中文键": "值", "nested": {"b": 2, "a": 1}}
    p1 = os.path.join(tmp_out, "one.json")
    p2 = os.path.join(tmp_out, "two.json")
    serialize.write_json(p1, payload)
    serialize.write_json(p2, payload)
    with open(p1, "rb") as h1, open(p2, "rb") as h2:
        assert h1.read() == h2.read()


def test_written_bytes_contain_no_cr(tmp_out):
    """CR 守门必须打在写盘产物上，不是只打在 dumps() 的返回值上。

    变异验证实测：往 write_atomic 的字节里注入 CR 时，只断言 dumps() 的测试不会红
    ——"写入的字节无 CR" 才是真正要保的性质（跨平台逐字节一致的前提）。
    """
    path = os.path.join(tmp_out, "cr.json")
    serialize.write_json(path, {"中文键": "值", "a": [1, 2]})
    with open(path, "rb") as handle:
        raw = handle.read()
    assert b"\r" not in raw, "写盘产物含 CR，跨平台逐字节一致不成立"
    assert raw.endswith(b"}\n"), "写盘产物必须以单个 LF 结尾"


def test_written_text_is_lf_only_multi_line(tmp_out):
    """多行产物的每一处换行都是 LF（不只是结尾）。"""
    path = os.path.join(tmp_out, "multi.json")
    serialize.write_json(path, {"b": 2, "a": 1, "c": {"z": 26, "y": 25}})
    with open(path, "rb") as handle:
        raw = handle.read()
    assert raw.count(b"\n") >= 4, "多行产物换行数异常，断言可能空转"
    assert raw.replace(b"\n", b"") != raw and b"\r" not in raw


def test_write_atomic_leaves_no_temp_files(tmp_out):
    serialize.write_json(os.path.join(tmp_out, "x.json"), {"a": 1})
    leftovers = [n for n in os.listdir(tmp_out) if n.startswith(".opslens-")]
    assert leftovers == []


def test_write_atomic_creates_parent_dirs(tmp_out):
    nested = os.path.join(tmp_out, "a", "b", "c.json")
    serialize.write_json(nested, {"a": 1})
    assert os.path.isfile(nested)


def test_write_atomic_cleans_temp_on_failure(tmp_out):
    class Boom(object):
        pass

    with pytest.raises(TypeError):
        serialize.write_json(os.path.join(tmp_out, "bad.json"), Boom())
    leftovers = [n for n in os.listdir(tmp_out) if n.startswith(".opslens-")]
    assert leftovers == []


def test_roundtrip_preserves_values(tmp_out):
    payload = {"k": {"n": None, "t": True, "f": 1.5, "s": "中文"}}
    path = os.path.join(tmp_out, "r.json")
    serialize.write_json(path, payload)
    assert serialize.read_json(path) == payload
