"""编排层：scan 阶段（模块 1 的落地编排）。

分层纪律（plan/02 §二）：编排层只做"发现 → 分发 → 合并 → 排序"，**零判定**。
阈值/口径参数由 CLI 从规则包读出后**以参数注入**给解析层，
保证解析层仍是纯函数（不读规则包、不读时钟、不写盘）。

本棒（M2）只落地 scan 阶段；aggregate / attribute / report 阶段随 M3/M5 接入。
"""

from . import schema
from .parsers import claude_config
from .parsers import claude_jsonl
from .parsers import codex_rollout
from .parsers import discovery

# 事件流产物的 schema 标识（唯一出处）
EVENTS_SCHEMA = "opslens.events/1"


def scan_home(home, max_error_chars=None):
    """解析 `home` 下的全部会话日志为统一事件流。

    返回 `(events, report)`：
      · `events` = `ToolCallEvent` 列表（未排序；排序由 `schema.events_to_payload` 统一做）
      · `report`  = 来源与覆盖声明（供报告"数据来源与覆盖声明"节 + CLI 摘要）
    """
    sources, skipped = discovery.discover_logs(home)

    events = []
    diagnostics = []
    versions_seen = {}
    session_tokens = {}

    for source in sources:
        kind = source["kind"]
        if kind == discovery.KIND_CLAUDE_JSONL:
            parsed, diags = claude_jsonl.scan_claude_jsonl(source["path"], max_error_chars)
        elif kind == discovery.KIND_CODEX_ROLLOUT:
            parsed, token_usage, diags = codex_rollout.scan_codex_rollout(
                source["path"], max_error_chars
            )
            if token_usage:
                session_tokens[source["relative"]] = token_usage
        else:
            raise ValueError("unknown source kind: {0}".format(kind))
        events.extend(parsed)
        for diag in diags:
            item = dict(diag)
            item["source"] = source["relative"]
            diagnostics.append(item)
        for event in parsed:
            if event.source_version:
                versions_seen.setdefault(event.source, set()).add(event.source_version)

    config_facts = claude_config.parse_claude_config(home)

    report = {
        "home": home,
        "schema": EVENTS_SCHEMA,
        "sources": [
            {"relative": item["relative"], "kind": item["kind"]} for item in sources
        ],
        "skipped": [
            {"relative": item["path"].replace("\\", "/"), "reason": item["reason"]}
            for item in skipped
        ],
        "schema_versions": dict(
            (source, sorted(values)) for source, values in sorted(versions_seen.items())
        ),
        "diagnostics": diagnostics,
        "session_token_usage": dict(sorted(session_tokens.items())),
        "config_facts": config_facts,
        "coverage_note": (
            "来源与覆盖声明：以上为本次实际扫描的日志文件与 schema 版本；"
            "未知版本或不可判别形态的日志不会被静默解析。"
        ),
    }
    return events, report


def build_events_payload(events, report):
    """事件流 → 确定性载荷（排序 + 来源声明），供 `serialize` 写盘。"""
    extra = {
        "home": report["home"],
        "sources": report["sources"],
        "schema_versions": report["schema_versions"],
        "coverage_note": report["coverage_note"],
    }
    return schema.events_to_payload(events, extra=extra)
