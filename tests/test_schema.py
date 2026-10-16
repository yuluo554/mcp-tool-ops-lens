"""IR 契约测试：三态语义、确定性排序、序列化。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from opslens import schema  # noqa: E402


def _event(**kw):
    base = dict(
        source="claude_code",
        source_version="2.1.233",
        session_id="s1",
        seq=1,
        timestamp="2026-10-16T00:00:00Z",
        server="fake-server",
        tool="tool_a",
    )
    base.update(kw)
    return schema.ToolCallEvent(**base)


def test_three_states_are_distinct():
    assert schema.STATUS_OK != schema.STATUS_ERROR != schema.STATUS_UNKNOWN


def test_default_status_is_unknown_not_ok():
    """缺失态绝不等同成功：默认必须是 unknown。"""
    assert _event().status == schema.STATUS_UNKNOWN


def test_unknown_status_is_accepted():
    assert _event(status="unknown").status == "unknown"


def test_bad_status_rejected():
    with pytest.raises(ValueError):
        _event(status="success")


def test_bad_source_rejected():
    with pytest.raises(ValueError):
        _event(source="cursor")


def test_tokens_none_is_not_zero():
    assert _event().tokens is None
    assert _event().to_dict()["tokens"] is None


def test_tokens_kept_as_four_separate_fields():
    ev = _event(tokens=schema.Tokens(100, 20, 5, 3))
    got = ev.to_dict()["tokens"]
    assert got == {"input": 100, "output": 20, "cache_read": 5, "cache_creation": 3}


def test_sort_key_uses_seq_not_insertion_order():
    later = _event(seq=9)
    earlier = _event(seq=2)
    assert sorted([later, earlier], key=lambda e: e.sort_key) == [earlier, later]


def test_events_to_payload_is_deterministic():
    events = [_event(seq=3), _event(seq=1), _event(seq=2)]
    first = schema.payload_to_json(schema.events_to_payload(events))
    second = schema.payload_to_json(schema.events_to_payload(list(reversed(events))))
    assert first == second


def test_equality_is_value_based():
    assert _event() == _event()
    assert _event(seq=1) != _event(seq=2)


def test_duration_none_means_unavailable_not_zero():
    ev = _event()
    assert ev.duration_ms is None
    assert ev.to_dict()["duration_ms"] is None
