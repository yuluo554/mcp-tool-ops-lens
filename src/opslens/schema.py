"""统一中间表示（IR）：ToolCallEvent。五模块的共同契约，定义只此一处（plan/02 §三）。"""

import json
from collections import namedtuple

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"

SOURCE_CLAUDE_CODE = "claude_code"
SOURCE_CODEX = "codex"

BUILTIN_SERVER = "<builtin>"

Tokens = namedtuple("Tokens", ["input", "output", "cache_read", "cache_creation"])

_TOKENS_KEYS = ("input", "output", "cache_read", "cache_creation")


class ToolCallEvent(object):
    """一次工具调用事件。

    status 是三态：ok / error / unknown。unknown 表示"日志未声明成败"，
    绝不等同成功（data/README.md §五 A）。
    tokens 为 None 表示该源/该条不提供 token 归因，不等于 0。
    """

    __slots__ = (
        "source",
        "source_version",
        "session_id",
        "seq",
        "timestamp",
        "server",
        "tool",
        "call_id",
        "status",
        "error_text",
        "tokens",
        "duration_ms",
        "turn_tokens_attributed",
        "notes",
    )

    def __init__(
        self,
        source,
        source_version,
        session_id,
        seq,
        timestamp,
        server,
        tool,
        call_id="",
        status=STATUS_UNKNOWN,
        error_text="",
        tokens=None,
        duration_ms=None,
        turn_tokens_attributed=False,
        notes=None,
    ):
        if source not in (SOURCE_CLAUDE_CODE, SOURCE_CODEX):
            raise ValueError("unknown source: {0}".format(source))
        if status not in (STATUS_OK, STATUS_ERROR, STATUS_UNKNOWN):
            raise ValueError("unknown status: {0}".format(status))
        self.source = source
        self.source_version = source_version
        self.session_id = session_id
        self.seq = int(seq)
        self.timestamp = timestamp
        self.server = server
        self.tool = tool
        self.call_id = call_id
        self.status = status
        self.error_text = error_text
        self.tokens = tokens
        self.duration_ms = duration_ms
        self.turn_tokens_attributed = bool(turn_tokens_attributed)
        self.notes = list(notes) if notes else []

    @property
    def sort_key(self):
        """确定性排序键：源行号 seq 保证同会话内稳定，不依赖数组下标或时钟。"""
        return (self.source, self.session_id, self.seq)

    def to_dict(self):
        tokens = None
        if self.tokens is not None:
            tokens = dict(zip(_TOKENS_KEYS, self.tokens))
        return {
            "source": self.source,
            "source_version": self.source_version,
            "session_id": self.session_id,
            "seq": self.seq,
            "timestamp": self.timestamp,
            "server": self.server,
            "tool": self.tool,
            "call_id": self.call_id,
            "status": self.status,
            "error_text": self.error_text,
            "tokens": tokens,
            "duration_ms": self.duration_ms,
            "turn_tokens_attributed": self.turn_tokens_attributed,
            "notes": list(self.notes),
        }

    def __eq__(self, other):
        if not isinstance(other, ToolCallEvent):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __repr__(self):
        return "ToolCallEvent({0}/{1}/{2}, status={3})".format(
            self.source, self.server, self.tool, self.status
        )


def tokens_to_dict(tokens):
    """Tokens -> 可序列化 dict（键序固定，供确定性写盘）。"""
    if tokens is None:
        return None
    return dict(zip(_TOKENS_KEYS, tokens))


def events_to_payload(events, extra=None):
    """事件流 -> 供 serialize 写盘的载荷（已排序，确定性）。"""
    ordered = sorted(events, key=lambda e: e.sort_key)
    payload = {"schema": "opslens.events/1", "count": len(ordered)}
    if extra:
        payload.update(extra)
    payload["events"] = [e.to_dict() for e in ordered]
    return payload


def payload_to_json(payload):
    return json.dumps(payload, ensure_ascii=False)
