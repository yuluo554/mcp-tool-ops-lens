"""Markdown 渲染器（模块 4 人读轨之一）。

**零判定**：本文件不读规则包、不 import 聚合层/归因层、不算任何比率——
一切数字与判定**只从 `report.json` 载荷里取**。本文件若出现 `BinOp(Div)`，
口径唯一性守门（`tests/test_aggregate.py::DIV_ALLOWED_FILES`）会判红。

**零字面量**：连小数保留位数都从载荷的 `inputs.rate_precision` 取（不写死），
与聚合层"精度只来自规则包"同源。

**无外链硬断言**：`render_markdown()` 返回前**常驻**调用
`guard.assert_no_external_resources()`——产物含任何外链构造即当场抛错（断网可开是交付硬项）。
"""

from . import guard


def _fmt(value, digits):
    """数值格式化（只排版，不改口径）。`None` → `n/a`（缺失不得看起来像 0）。"""
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and digits is not None:
        text = ("{0:." + str(digits) + "f}").format(value)
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def _formatter(payload):
    """按载荷声明的精度造一个格式化闭包（精度不写死在本文件）。"""
    digits = payload.get("inputs", {}).get("rate_precision")
    return lambda value: _fmt(value, digits)


def _bullets(items):
    return ["- " + item for item in items]


def render_markdown(payload):
    """`opslens.report/1` 载荷 → Markdown 文本（结尾换行，LF 行尾）。"""
    f = _formatter(payload)
    lines = []
    summary = payload["summary"]

    lines.append("# opslens 删换建议报告")
    lines.append("")
    lines.append("> schema：`{0}`".format(payload["schema"]))
    lines.append("> 定位：{0}".format(payload["positioning"]["statement"]))
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.extend(
        _bullets(
            [
                "server 数：{0}".format(f(summary["servers"])),
                "调用总数：{0}（error {1} / unknown {2}）".format(
                    f(summary["calls_total"]), f(summary["calls_error"]), f(summary["calls_unknown"])
                ),
                "建议条数：{0}（其中\"建议移除\" {1}）".format(
                    f(summary["suggestions"]), f(summary["remove_candidate"])
                ),
                "\"数据不足\"降级条数：{0}".format(f(summary["insufficient_data"])),
                "未生效规则条数：{0}".format(f(summary["ineffective_rules"])),
            ]
        )
    )
    lines.append("")

    # ① 数据来源与覆盖声明
    lines.append("## 一、数据来源与覆盖声明")
    lines.append("")
    declaration = payload["source_declaration"]
    lines.extend(
        _bullets(
            [
                "扫描根目录：`{0}`".format(f(declaration.get("home"))),
                "输入 schema：events `{0}` / aggregate `{1}` / attribute `{2}`".format(
                    f(payload["inputs"]["events_schema"]),
                    f(payload["inputs"]["aggregate_schema"]),
                    f(payload["inputs"]["attribute_schema"]),
                ),
            ]
        )
    )
    lines.append("")
    lines.append("| 来源文件 | 类型 |")
    lines.append("|---|---|")
    for item in declaration["sources"]:
        lines.append("| {0} | {1} |".format(item["relative"], item["kind"]))
    if not declaration["sources"]:
        lines.append("| （无） | — |")
    lines.append("")
    versions = "；".join(
        "{0} = {1}".format(source, ", ".join(values))
        for source, values in sorted(declaration["schema_versions"].items())
    ) or "（无）"
    lines.extend(
        _bullets(
            [
                "schema 版本：{0}".format(versions),
                declaration["coverage_note"] or "",
                declaration["totals_note"],
            ]
        )
    )
    lines.append("")

    # ② unknown / 样本缺失独立分区
    unknown = payload["unknown_partition"]
    lines.append("## 二、{0}".format(unknown["title"]))
    lines.append("")
    lines.append(unknown["note"])
    lines.append("")
    lines.extend(
        _bullets(
            [
                "unknown 调用：{0} / 总调用 {1}".format(
                    f(unknown["calls_unknown"]), f(unknown["calls_total"])
                ),
                "token 缺失样本：{0}".format(f(unknown["token_missing"])),
                "耗时缺失样本：{0}".format(f(unknown["duration_missing"])),
            ]
        )
    )
    lines.append("")
    lines.append("| source | server | 总数 | ok | error | unknown | token 缺失 | 耗时缺失 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in unknown["by_server"]:
        lines.append(
            "| {0} | {1} | {2} | {3} | {4} | {5} | {6} | {7} |".format(
                row["source"],
                row["server"],
                f(row["calls_total"]),
                f(row["calls_ok"]),
                f(row["calls_error"]),
                f(row["calls_unknown"]),
                f(row["token_missing"]),
                f(row["duration_missing"]),
            )
        )
    lines.append("")
    lines.append("> {0}".format(unknown["unattributed"]["note"]))
    lines.append("")

    # ③ 建议清单
    lines.append("## 三、建议清单")
    lines.append("")
    if not payload["suggestions"]:
        lines.append("本次统计未触发任何建议（无 server 同时满足失败率与样本量门槛）。")
        lines.append("")
    for entry in payload["suggestions"]:
        lines.append("### `{0}` · {1}/{2}".format(entry["type"], entry["source"], entry["server"]))
        lines.append("")
        lines.extend(
            _bullets(
                [
                    "口径：`{0}` = {1}".format(entry["metric"], f(entry["value"])),
                    "分子/分母：{0} / {1}".format(f(entry["numerator"]), f(entry["denominator"])),
                    "样本量：{0}".format(f(entry["sample_size"])),
                    "阈值取值：{0}".format(
                        ", ".join(
                            "{0}={1}".format(key, f(value))
                            for key, value in sorted(entry["threshold"].items())
                        )
                    ),
                    "样本门槛：{0}".format(
                        ", ".join(
                            "{0}={1}".format(key, f(value))
                            for key, value in sorted(entry["sample_requirement"].items())
                        )
                    ),
                    entry["basis"],
                ]
            )
        )
        lines.append("")

    # 数据不足降级（独立分区）
    lines.append("### 数据不足（降级，不出建议）")
    lines.append("")
    if not payload["insufficient_data"]:
        lines.append("无。")
        lines.append("")
    else:
        lines.append("| 轴 | source | server | 观测样本 | 需要样本 | 原因 |")
        lines.append("|---|---|---|---|---|---|")
        for item in payload["insufficient_data"]:
            lines.append(
                "| {0} | {1} | {2} | {3} | {4} | {5} |".format(
                    item["axis"],
                    item["source"],
                    item["server"],
                    f(item["observed_sample"]),
                    f(item["required_sample"]),
                    item["reason"],
                )
            )
        lines.append("")
    ineffective_text = "；".join(
        "{0}（{1}）".format(item["id"], "，".join(item["reasons"]))
        for item in payload["failure_attribution"]["ineffective_rules"]
    ) or "（无）"
    lines.append(
        "> 未生效规则清单（不参与匹配，其覆盖类别落 `other`）：{0}".format(ineffective_text)
    )
    lines.append("")

    # ④ 失败模式归因
    attribution = payload["failure_attribution"]
    lines.append("## 四、失败模式归因（规则匹配，非 AI 评分）")
    lines.append("")
    lines.append(
        "失败调用 {0} 次：命中规则 {1} 次 / 落 other {2} 次。".format(
            f(attribution["calls_error"]), f(attribution["matched"]), f(attribution["other"])
        )
    )
    lines.append("")
    lines.append("| 类别 | 次数 |")
    lines.append("|---|---|")
    for item in attribution["by_category"]:
        lines.append("| {0} | {1} |".format(item["category"], item["calls"]))
    lines.append("")
    lines.append("生效规则：{0}".format(", ".join(attribution["effective_rule_ids"]) or "（无）"))
    lines.append("")
    if attribution["ineffective_rules"]:
        lines.append("未生效规则（原因）：")
        lines.append("")
        lines.extend(
            _bullets(
                [
                    "`{0}`：{1}".format(item["id"], "，".join(item["reasons"]))
                    for item in attribution["ineffective_rules"]
                ]
            )
        )
        lines.append("")

    # ⑤ 排名
    lines.append("## 五、排名（Top 清单）")
    lines.append("")
    lines.append(payload["rankings"]["note"])
    lines.append("")
    for title, key in (("失败率 Top", "failure_rate_top"), ("token 开销 Top", "turn_token_top")):
        lines.append("### {0}".format(title))
        lines.append("")
        rows = payload["rankings"][key]
        if not rows:
            lines.append("（无可排名维度）")
            lines.append("")
            continue
        lines.append("| source | server | 值 |")
        lines.append("|---|---|---|")
        for row in rows:
            lines.append("| {0} | {1} | {2} |".format(row["source"], row["server"], f(row["value"])))
        lines.append("")

    # ⑥ 定位宣言
    lines.append("## 六、定位与声明")
    lines.append("")
    lines.extend(
        _bullets([payload["positioning"]["statement"], payload["positioning"]["not_auto_modify"]])
    )
    lines.append("")

    return guard.assert_no_external_resources("\n".join(lines) + "\n")
