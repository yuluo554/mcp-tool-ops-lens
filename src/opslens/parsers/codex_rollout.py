"""Codex rollout 解析（`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`）→ `ToolCallEvent` 流。

口径全部来自 data/README §五 D（M1 本机实测）：

- **调用**：`response_item` 且 `payload.type` ∈ `function_call` / `custom_tool_call`。
- **成败**：**无显式 `is_error`**。只认输出文本里的 `Exit code: N`——`N == 0` → `ok`，
  `N != 0` → `error`，**无该文本 → `unknown`**（缺失 ≠ 成功）。
  `payload.status` 实测恒为 `completed`（哑值），**绝不当成败判据**。
- **耗时**：输出文本 `Wall time: N seconds` → `duration_ms`。
- **token**：只在 `event_msg/token_count`，是**会话/轮级**，与单次调用无绑定 →
  **不摊到单次工具调用**（K3）。故 IR 的 `tokens=None`、`turn_tokens_attributed=False`，
  会话级汇总由 `session_token_usage` 单独返回。
- **server**：原样记 `"<codex>"`，**不套 Claude 的 `mcp__` 前缀规则**（实测无该命名）。
- **`seq` = 源行号（K11）**。

纯函数：不读规则包、不读时钟、不写盘。
"""

import re

from .. import exit_codes
from .. import schema
from . import common
from . import versions

CODEX_SERVER = "<codex>"

CALL_TYPES = ("function_call", "custom_tool_call")
OUTPUT_TYPES = ("function_call_output", "custom_tool_call_output")

# 输出文本模式（文本模式，非模型；plan/03 §1.1）
_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)")
_WALL_TIME_RE = re.compile(r"Wall time:\s*([0-9]+(?:\.[0-9]+)?)\s*seconds")

_SESSION_META_TYPE = "session_meta"
_RESPONSE_ITEM_TYPE = "response_item"
_EVENT_MSG_TYPE = "event_msg"
_TOKEN_COUNT_TYPE = "token_count"

# 秒 → 毫秒的换算基数（单位换算，不是阈值口径）
_MS_PER_SECOND = 1000


def _parse_exit_code(output_text):
    """从输出文本取退出码；无 `Exit code:` 文本 → None（第三态）。"""
    match = _EXIT_CODE_RE.search(output_text or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _parse_wall_time_ms(output_text):
    """`Wall time: N seconds` → 毫秒整数；不可得 → None（不代入均值）。"""
    match = _WALL_TIME_RE.search(output_text or "")
    if not match:
        return None
    return int(round(float(match.group(1)) * _MS_PER_SECOND))


def scan_codex_rollout(path, max_error_chars=None):
    """解析一个 Codex rollout：返回 `(events, session_token_usage, diagnostics)`。

    `session_token_usage` 是**会话级** token（K3），键为 token 名 → 整数；
    取 `total_token_usage`（会话累计），无则回落到最后一次 `last_token_usage`。
    """
    diagnostics = []
    cli_version = None
    calls = []
    outputs = {}
    token_usage = None
    session_id = common.session_id_from_path(path)

    for line_no, row in common.iter_jsonl(path):
        row_type = row.get("type")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if row_type == _SESSION_META_TYPE:
            candidate = payload.get("cli_version")
            if isinstance(candidate, str) and candidate:
                cli_version = candidate
            for key in ("id", "session_id"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    session_id = value
                    break
        elif row_type == _RESPONSE_ITEM_TYPE:
            payload_type = payload.get("type")
            if payload_type in CALL_TYPES:
                calls.append(
                    {
                        "seq": line_no,
                        "call_id": payload.get("call_id") or payload.get("id") or "",
                        "tool": payload.get("name") or "",
                        "timestamp": row.get("timestamp") or "",
                    }
                )
            elif payload_type in OUTPUT_TYPES:
                outputs[payload.get("call_id") or ""] = common.text_of_content(payload.get("output"))
        elif row_type == _EVENT_MSG_TYPE and payload.get("type") == _TOKEN_COUNT_TYPE:
            info = payload.get("info")
            if isinstance(info, dict):
                usage = info.get("total_token_usage")
                if not isinstance(usage, dict):
                    usage = info.get("last_token_usage")
                if isinstance(usage, dict):
                    token_usage = dict(
                        (key, value) for key, value in usage.items() if isinstance(value, int)
                    )

    # 版本检测（检测键路径 session_meta.payload.cli_version；不在集内 → exit 4）
    versions.check_codex_cli_version(cli_version)

    events = []
    for call in calls:
        output_text = outputs.get(call["call_id"])
        notes = []
        if output_text is None:
            status = schema.STATUS_UNKNOWN
            error_text = ""
            notes.append("output_missing")
            duration_ms = None
        else:
            exit_code = _parse_exit_code(output_text)
            if exit_code is None:
                status = schema.STATUS_UNKNOWN
                notes.append("exit_code_undeclared")
            elif exit_code == 0:
                status = schema.STATUS_OK
            else:
                status = schema.STATUS_ERROR
            duration_ms = _parse_wall_time_ms(output_text)
            if duration_ms is None:
                notes.append("wall_time_missing")
            error_text = (
                common.truncate_error_text(output_text, max_error_chars)
                if status == schema.STATUS_ERROR
                else ""
            )
        events.append(
            schema.ToolCallEvent(
                source=schema.SOURCE_CODEX,
                source_version=cli_version or "",
                session_id=session_id,
                seq=call["seq"],
                timestamp=call["timestamp"],
                server=CODEX_SERVER,
                tool=call["tool"],
                call_id=call["call_id"],
                status=status,
                error_text=error_text,
                tokens=None,  # K3：Codex 不按工具归因 token
                duration_ms=duration_ms,
                turn_tokens_attributed=False,
                notes=notes,
            )
        )

    matched_ids = set(call["call_id"] for call in calls)
    for call_id in sorted(outputs):
        if call_id not in matched_ids:
            diagnostics.append({"kind": "dangling_tool_output", "call_id": call_id})

    return events, token_usage, diagnostics


def parse_codex_rollout(path, max_error_chars=None):
    """纯解析入口：只返回事件流（会话级 token 见 `scan_codex_rollout`）。"""
    events, _usage, _diagnostics = scan_codex_rollout(path, max_error_chars)
    return events
