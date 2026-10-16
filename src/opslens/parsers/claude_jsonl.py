"""Claude Code 会话日志解析（`~/.claude/projects/*/*.jsonl`）→ `ToolCallEvent` 流。

口径全部来自 data/README §五（M1 本机实测），本模块不自行发明语义：

- **成败三态（K1 硬口径）**：`tool_result.is_error is True` → `error`；
  `is False` → `ok`；**键缺失 → `unknown`**（缺失 ≠ 成功，绝不默认成功）。
- **token = 调用轮次归属（K2）**：取 `assistant.message.usage` 四项**分列**；
  该 assistant 消息即"本次工具调用所在轮次"，不是"工具自身消耗"。
- **耗时不可得（K4）**：Claude jsonl 无按工具耗时字段 → `duration_ms=None`。
  绝不用 `~/.claude.json` 的 `lastToolDuration` 冒充（那是项目级"最后一次"值）。
- **`tool_use.input` 不进 IR**（可能含源码/参数，plan/04 §二 第 4 条）。
- **`seq` = 源行号（K11）**：取声明该 `tool_use` 的行号，不是数组下标。

纯函数：不读规则包、不读时钟、不写盘。错误文本截断上限由调用方注入。
"""

from .. import schema
from . import common
from . import versions

# 非 `mcp__` 前缀的内置工具归到此 server 段（plan/03 §1.1）
_BUILTIN_PREFIX = "mcp__"

# 三态判定的字段名（唯一出处；缺失即第三态）
_IS_ERROR_KEY = "is_error"

# 次生信号键（进 notes 供审计，**不改写** is_error 判定，data/README §五 A）
_TOOL_USE_RESULT_KEY = "toolUseResult"


def _split_tool_name(name):
    """`mcp__<server>__<tool>` → (server, tool)；非该形态 → (`<builtin>`, 原名)。"""
    if isinstance(name, str) and name.startswith(_BUILTIN_PREFIX):
        parts = name.split("__")
        if len(parts) >= 3 and parts[1]:
            return parts[1], "__".join(parts[2:])
    return schema.BUILTIN_SERVER, name if isinstance(name, str) else ""


def _tokens_from_usage(usage):
    """`message.usage` → `Tokens`（四项分列，K2）。缺失 → None（≠ 0）。"""
    if not isinstance(usage, dict):
        return None
    keys = (
        ("input_tokens", "input"),
        ("output_tokens", "output"),
        ("cache_read_input_tokens", "cache_read"),
        ("cache_creation_input_tokens", "cache_creation"),
    )
    if not any(raw in usage for raw, _ in keys):
        return None
    values = []
    for raw, _name in keys:
        value = usage.get(raw)
        values.append(value if isinstance(value, int) else 0)
    return schema.Tokens(*values)


def _session_id_of(row, fallback):
    for key in ("sessionId", "session_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def _result_status(block, notes):
    """三态判定（K1）。返回 (status, error_text_raw)。

    只认 `is_error is True` 为 error、`is False` 为 ok；**键缺失 = unknown**。
    出现非布尔取值（IR 未覆盖的新形态）→ 降级 unknown + 注记，**不猜**（plan/03 §1.2）。
    """
    if _IS_ERROR_KEY not in block:
        notes.append("status_undeclared")
        return schema.STATUS_UNKNOWN, common.text_of_content(block.get("content"))
    value = block[_IS_ERROR_KEY]
    if value is True:
        return schema.STATUS_ERROR, common.text_of_content(block.get("content"))
    if value is False:
        return schema.STATUS_OK, ""
    notes.append("unrecognized_is_error_type")
    return schema.STATUS_UNKNOWN, common.text_of_content(block.get("content"))


def scan_claude_jsonl(path, max_error_chars=None):
    """解析一个 Claude jsonl 文件：返回 `(events, diagnostics)`。

    `diagnostics` 记录无法进入 IR 的事实（如悬空 `tool_result`、版本漂移），
    供 CLI 打印到 stderr —— 静默丢弃会让计数偏低，属"把未声明态洗成不存在"。
    """
    diagnostics = []
    version_seen = []
    calls = []
    results = {}

    for line_no, row in common.iter_jsonl(path):
        row_type = row.get("type")

        version = row.get("version")
        if isinstance(version, str) and version and version not in version_seen:
            version_seen.append(version)

        if row_type == "assistant":
            message = row.get("message") or {}
            content = message.get("content") or []
            usage = _tokens_from_usage(message.get("usage"))
            if not isinstance(content, list):
                diagnostics.append({"line": line_no, "kind": "unexpected_content_shape"})
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_use"):
                    continue
                server, tool = _split_tool_name(block.get("name"))
                calls.append(
                    {
                        "line": line_no,
                        "seq": line_no,
                        "call_id": block.get("id") or "",
                        "server": server,
                        "tool": tool,
                        "session_id": _session_id_of(row, common.session_id_from_path(path)),
                        "timestamp": row.get("timestamp") or "",
                        "version": version if isinstance(version, str) else "",
                        "tokens": usage,
                    }
                )
        elif row_type == "user":
            message = row.get("message") or {}
            content = message.get("content") or []
            if not isinstance(content, list):
                diagnostics.append({"line": line_no, "kind": "unexpected_content_shape"})
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                notes = []
                status, raw_text = _result_status(block, notes)
                tool_use_result = row.get(_TOOL_USE_RESULT_KEY)
                if isinstance(tool_use_result, dict):
                    if tool_use_result.get("interrupted") is True:
                        notes.append("interrupted")
                    stderr = tool_use_result.get("stderr")
                    if isinstance(stderr, str) and stderr.strip():
                        notes.append("stderr_nonempty")
                results[block.get("tool_use_id") or ""] = {
                    "status": status,
                    "error_text": raw_text,
                    "notes": notes,
                }

    # 版本检测（唯一入口，显式支持集；不在集内 → exit 4）
    if not version_seen:
        versions.check_claude_version(None)
    for version in version_seen:
        versions.check_claude_version(version)
    source_version = version_seen[0] if version_seen else ""
    if len(version_seen) > 1:
        diagnostics.append({"kind": "multiple_versions_in_file", "versions": list(version_seen)})

    events = []
    for call in calls:
        matched = results.get(call["call_id"])
        notes = []
        if matched is None:
            status = schema.STATUS_UNKNOWN
            error_text = ""
            notes.append("result_missing")
        else:
            status = matched["status"]
            notes = list(matched["notes"])
            error_text = common.truncate_error_text(matched["error_text"], max_error_chars)
            if status == schema.STATUS_UNKNOWN and error_text:
                # 本机实测形态：缺失态中约 14.9% 含错误文本。文本保留供审计，
                # 但 status 仍是 unknown —— **不进失败率分母**（K1）。
                notes.append("error_text_present_on_unknown")
            if status == schema.STATUS_OK:
                error_text = ""
        events.append(
            schema.ToolCallEvent(
                source=schema.SOURCE_CLAUDE_CODE,
                source_version=call["version"] or source_version,
                session_id=call["session_id"],
                seq=call["seq"],
                timestamp=call["timestamp"],
                server=call["server"],
                tool=call["tool"],
                call_id=call["call_id"],
                status=status,
                error_text=error_text,
                tokens=call["tokens"],
                duration_ms=None,  # K4：Claude 侧按工具耗时不可得
                turn_tokens_attributed=True,  # K2：token 归属调用轮次
                notes=notes,
            )
        )

    matched_ids = set(call["call_id"] for call in calls)
    for tool_use_id in sorted(results):
        if tool_use_id not in matched_ids:
            diagnostics.append({"kind": "dangling_tool_result", "tool_use_id": tool_use_id})

    return events, diagnostics


def parse_claude_jsonl(path, max_error_chars=None):
    """纯解析入口：只返回事件流（诊断见 `scan_claude_jsonl`）。"""
    events, _diagnostics = scan_claude_jsonl(path, max_error_chars)
    return events
