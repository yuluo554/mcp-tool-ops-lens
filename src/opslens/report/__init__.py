"""模块 4 · 报告层（单一渲染源 `report.json` → MD / HTML）。

分层纪律（plan/02 §二、plan/03 §4.2）：
  · 本包**不读规则包**（阈值以参数注入）、**不 import 聚合层/归因层**、
    **不算任何比率**（AST 守门：本包内无 `BinOp(Div)`）。
  · 一切数字与判定**只来自 `report.json`**；`markdown.py` / `html.py` 只做排版。
  · "两格式内容一致"是**结构性质**（同一份 `report.json` 渲染两遍），不是人工比对。

本模块是**建议层与报告装配**（模块 4）：把 `aggregate` / `attribute` 载荷（已算好的比率与计数）
加上阈值参数，装配成 `opslens.report/1` 载荷，再交给两个渲染器。

`report.json` 必含章节（plan/03 §4.2）：
  ① `source_declaration` —— 数据来源与覆盖声明（扫了哪些路径、哪些源、schema 版本）
  ② `unknown_partition` —— `unknown`/样本缺失独立分区（**不混入统计**）
  ③ `suggestions` —— 建议清单（每条附口径 + 阈值取值 + 分子/分母 + 样本量）
  ④ `failure_attribution.ineffective_rules` —— 未生效规则清单（原因）
  ⑤ `positioning` —— 定位宣言 + "建议仅供参考，不自动修改配置"声明
"""

from . import guard
from . import suggestions as suggestions_module

# 报告载荷的 schema 标识（唯一出处）
REPORT_SCHEMA = "opslens.report/1"

# 报告正文里"未知态独立分区"的固定标题（渲染器与守门共用一处）
UNKNOWN_SECTION_TITLE = "未知态与样本缺失（独立分区，不混入统计）"

POSITIONING_STATEMENT = (
    "本报告由本机会话日志**只读**统计得出：统计为确定性计数，归因是规则匹配，"
    "全程不引入任何模型、零上传、零遥测。"
)
NOT_AUTO_MODIFY_STATEMENT = (
    "建议仅供参考，不自动修改配置：本工具**绝不**增删改任何 MCP server 配置或用户设置，"
    "一切处置由使用者自行判断与执行。"
)


def _totals_note(agg):
    return (
        "汇总口径与 server 级同源（对账等式：ok + error + unknown == 总数）；"
        "失败率分母不含 unknown；token 四项分列不合并。"
    )


def _unknown_partition(agg, attr):
    """② `unknown`/样本缺失独立分区：**不混入统计**（plan/03 §4.2 必含章节）。

    这里只**摘取**聚合载荷里已经算好的 `calls_unknown` / `token_missing` /
    `duration_missing`，不重算任何比率——"未声明"必须与"成功"分栏显示。
    """
    by_server = []
    for row in agg["server_level"]:
        by_server.append(
            {
                "source": row["source"],
                "server": row["server"],
                "calls_total": row["calls_total"],
                "calls_ok": row["calls_ok"],
                "calls_error": row["calls_error"],
                "calls_unknown": row["calls_unknown"],
                "token_missing": row["token_missing"],
                "duration_missing": row["duration_missing"],
            }
        )
    totals = agg["totals"]
    duration_missing = sum(row["duration_missing"] for row in agg["server_level"])
    return {
        "title": UNKNOWN_SECTION_TITLE,
        "note": (
            "unknown = 日志未声明成败（缺失 is_error 键），**既非成功也非失败**："
            "它不进失败率分母，也不参与归因；token/duration 缺失同理，缺失 ≠ 0。"
        ),
        "calls_unknown": totals["calls_unknown"],
        "calls_total": totals["calls_total"],
        "token_missing": totals["token_missing"],
        "duration_missing": duration_missing,
        "by_server": by_server,
        "unattributed": {
            "note": (
                "未参与归因的失败/未知：归因只消费 status=error 的记录；"
                "unknown 记录即便带错误文本也不参与归因（未声明成败 ≠ 失败）。"
            ),
            "calls_error": attr["totals"]["calls_error"],
            "calls_unknown": totals["calls_unknown"],
        },
    }


def _failure_attribution(attr):
    """④ 失败分类分布 + 未生效规则清单（原因）——原样取自归因载荷，不重算。"""
    return {
        "categories": list(attr["categories"]),
        "by_category": list(attr["by_category"]),
        "matched": attr["totals"]["matched"],
        "other": attr["totals"].get("other", 0),
        "calls_error": attr["totals"]["calls_error"],
        "effective_rule_ids": list(attr["effective_rule_ids"]),
        "ineffective_rules": [dict(item) for item in attr["ineffective_rules"]],
        "matched_patterns": [dict(item) for item in attr["matched_patterns"]],
        "coverage_note": attr["coverage_note"],
    }


def _collect_suggestions(agg, thresholds):
    """逐 server 跑建议层（两级轴独立判定），返回 (建议, 数据不足)。"""
    found = []
    insufficient = []
    for row in agg["server_level"]:
        outcome = suggestions_module.evaluate_server(row, thresholds)
        found.extend(outcome["suggestions"])
        insufficient.extend(outcome["insufficient"])
    return suggestions_module.sort_suggestions(found), suggestions_module.sort_insufficient(insufficient)


def _rank(server_rows, key):
    """按某轴降序排名（`None` 排最后）；并列时按 (source, server) 兜底保证确定性。

    只做**取载荷里已算好的值**与排序，不重算任何比率。
    """
    ranked = [row for row in server_rows if row.get(key) is not None]
    ranked.sort(key=lambda row: (-row[key], row["source"], row["server"]))
    return [{"source": row["source"], "server": row["server"], "value": row[key]} for row in ranked]


def _rankings(server_rows):
    """失败率 Top 与 token 开销 Top（模块 4 输出要求：两类 Top 清单）。"""
    return {
        "failure_rate_top": _rank(server_rows, "failure_rate"),
        "turn_token_top": _rank(server_rows, "turn_token_avg"),
        "note": (
            "排名只按聚合载荷里已算好的 failure_rate / turn_token_avg 排序，本层不重算；"
            "值为 null（分母为 0 或无样本）的维度不参与排名。"
        ),
    }


def build_report(events_report, agg_payload, attr_payload, thresholds, coverage_declaration=None):
    """装配 `opslens.report/1` 载荷（唯一渲染源）。

    `events_report` = `pipeline.scan_home` 的 report（来源/版本声明）；
    `agg_payload` / `attr_payload` = 模块 2/3 的载荷（**已算好的**数字，本层不重算）；
    `thresholds` = 由 CLI 从 `thresholds.json` 注入（本层不读规则包）。
    """
    suggestions, insufficient = _collect_suggestions(agg_payload, thresholds)
    remove_count = len([item for item in suggestions if item["type"] == suggestions_module.SUGGESTION_REMOVE])
    server_rows = [dict(row) for row in agg_payload["server_level"]]

    declaration = {
        "home": events_report.get("home"),
        "sources": [dict(item) for item in events_report.get("sources") or []],
        "schema_versions": dict(events_report.get("schema_versions") or {}),
        "coverage_note": events_report.get("coverage_note"),
        "totals": dict(agg_payload["totals"]),
        "totals_note": _totals_note(agg_payload),
    }
    if coverage_declaration is not None:
        declaration["benchmark_coverage"] = coverage_declaration

    payload = {
        "schema": REPORT_SCHEMA,
        "inputs": {
            "events_schema": events_report.get("schema"),
            "aggregate_schema": agg_payload.get("schema"),
            "attribute_schema": attr_payload.get("schema"),
            "rate_precision": agg_payload.get("rate_precision"),
        },
        "source_declaration": declaration,
        "unknown_partition": _unknown_partition(agg_payload, attr_payload),
        "failure_attribution": _failure_attribution(attr_payload),
        "server_metrics": server_rows,
        "tool_metrics": [dict(row) for row in agg_payload["tool_level"]],
        "rankings": _rankings(server_rows),
        "suggestions": suggestions,
        "insufficient_data": insufficient,
        "positioning": {
            "statement": POSITIONING_STATEMENT,
            "not_auto_modify": NOT_AUTO_MODIFY_STATEMENT,
        },
        "summary": {
            "servers": agg_payload["totals"]["servers"],
            "calls_total": agg_payload["totals"]["calls_total"],
            "calls_error": agg_payload["totals"]["calls_error"],
            "calls_unknown": agg_payload["totals"]["calls_unknown"],
            "suggestions": len(suggestions),
            "remove_candidate": remove_count,
            "insufficient_data": len(insufficient),
            "ineffective_rules": len(payload_ineffective(attr_payload)),
        },
    }
    return payload


def payload_ineffective(attr_payload):
    """未生效规则清单（供摘要计数与渲染共用，避免两处各数一遍）。"""
    return attr_payload.get("ineffective_rules") or []


def render(payload, out_dir):
    """渲染出口：`report.json` + `report.md` + `report.html` 三份落盘。

    返回三份产物的路径字典。渲染前两个渲染器**各自常驻** `assert_no_external_resources`。
    """
    import os

    from .. import serialize
    from . import html as html_module
    from . import markdown as markdown_module

    json_path = os.path.join(out_dir, "report.json")
    md_path = os.path.join(out_dir, "report.md")
    html_path = os.path.join(out_dir, "report.html")

    serialize.write_json(json_path, payload)
    md_text = markdown_module.render_markdown(payload)
    html_text = html_module.render_html(payload)
    serialize.write_atomic(md_path, md_text)
    serialize.write_atomic(html_path, html_text)
    return {"json": json_path, "markdown": md_path, "html": html_path}


def exit_code_for(payload):
    """退出码语义（README 明示）：命中"建议移除" → `1`（检出问题），否则 `0`。

    只读载荷里已算好的 `summary.remove_candidate`，不重算判定。
    """
    from .. import exit_codes

    if payload["summary"]["remove_candidate"]:
        return exit_codes.EXIT_FINDINGS
    return exit_codes.EXIT_OK
