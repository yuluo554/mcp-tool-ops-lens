"""编排层：scan / aggregate / attribute 三阶段（模块 1–3 的落地编排）。

分层纪律（plan/02 §二）：编排层只做"发现 → 分发 → 合并 → 排序"，**零判定**。
阈值/口径参数由 CLI 从规则包读出后**以参数注入**给解析层与聚合层，
保证解析层仍是纯函数（不读规则包、不读时钟、不写盘）。

本棒（M5）在 M3 的 attribute 阶段之上接上 report 阶段（模块 4）；
bench 阶段由模块 5 自行编排（M4）。
"""

from . import attribute as attribute_module
from . import aggregate as aggregate_module
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


def events_from_payload(payload):
    """事件流载荷 → `ToolCallEvent` 列表（`scan --out` 产物的读入通路）。

    读入时校验 schema 标识：不认识的载荷形态一律**报数据不可用**，
    绝不按最宽松假设解析（与解析层的版本检测同源纪律）。
    """
    from . import exit_codes

    if not isinstance(payload, dict):
        raise exit_codes.DataUnavailableError("事件流产物顶层必须是对象")
    if payload.get("schema") != EVENTS_SCHEMA:
        raise exit_codes.DataUnavailableError(
            "事件流产物 schema 不是 {0}：{1}".format(EVENTS_SCHEMA, payload.get("schema"))
        )
    events = []
    for item in payload.get("events") or []:
        tokens = item.get("tokens")
        if tokens is not None:
            tokens = schema.Tokens(
                tokens.get("input", 0),
                tokens.get("output", 0),
                tokens.get("cache_read", 0),
                tokens.get("cache_creation", 0),
            )
        events.append(
            schema.ToolCallEvent(
                source=item["source"],
                source_version=item.get("source_version") or "",
                session_id=item["session_id"],
                seq=item["seq"],
                timestamp=item.get("timestamp") or "",
                server=item["server"],
                tool=item["tool"],
                call_id=item.get("call_id") or "",
                status=item["status"],
                error_text=item.get("error_text") or "",
                tokens=tokens,
                duration_ms=item.get("duration_ms"),
                turn_tokens_attributed=item.get("turn_tokens_attributed", False),
                notes=item.get("notes") or [],
            )
        )
    return events


def aggregate_events(events, rules):
    """编排：事件流 → 聚合载荷（模块 2）。零判定，直接转交 `aggregate.aggregate`。"""
    return aggregate_module.aggregate(events, rules)


def attribute_events(events, rules):
    """编排：事件流 → 归因载荷（模块 3）。零判定，直接转交 `attribute.attribute`。"""
    return attribute_module.attribute(events, rules)


def report_events(events_report, agg_payload, attr_payload, rules, coverage_declaration=None):
    """编排：三份载荷 + 阈值 → 报告载荷（模块 4）。

    零判定：编排层只把**已算好的**数字与**以参数注入**的阈值转交给报告层装配，
    自身不算任何比率、不读规则包（阈值从 `rules.thresholds` 摘出后传入）。
    """
    from . import report as report_module

    return report_module.build_report(
        events_report,
        agg_payload,
        attr_payload,
        rules.thresholds,
        coverage_declaration=coverage_declaration,
    )
