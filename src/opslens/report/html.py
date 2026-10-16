"""HTML 渲染器（模块 4 人读轨之一；**内联 CSS、零外链、断网可开**）。

**零判定**：本文件不读规则包、不 import 聚合层/归因层、不算任何比率——
一切数字与判定**只从 `report.json` 载荷里取**。本文件若出现 `BinOp(Div)`，
口径唯一性守门（`tests/test_aggregate.py::DIV_ALLOWED_FILES`）会判红。

**零字面量**：小数保留位数从载荷的 `inputs.rate_precision` 取（不写死）。

**无外链硬断言**：`render_html()` 返回前**常驻**调用
`guard.assert_no_external_resources()`——样式全部内联在 `<style>` 里，**无** `<link>`、
**无** `<script>`、**无** `src=`/`href=` 属性、**无** `http(s)://`，断网可开。
"""

from html import escape as _escape

from . import guard

# 内联样式表（唯一 CSS 落点；不含 @import / url(...) 等外链构造）
_STYLE = """
:root { color-scheme: light; }
body { margin: 0; padding: 2rem; font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
       line-height: 1.6; color: #1f2328; background: #ffffff; }
h1 { font-size: 1.6rem; border-bottom: 2px solid #d0d7de; padding-bottom: .5rem; }
h2 { font-size: 1.25rem; margin-top: 2rem; border-bottom: 1px solid #eaeef2; padding-bottom: .3rem; }
h3 { font-size: 1.05rem; margin-top: 1.25rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; font-size: .92rem; }
th, td { border: 1px solid #d0d7de; padding: .35rem .6rem; text-align: left; }
th { background: #f6f8fa; }
code { background: #f6f8fa; padding: .1rem .3rem; border-radius: 3px; font-size: .9em; }
blockquote { margin: .5rem 0; padding: .4rem .8rem; border-left: 4px solid #d0d7de; color: #57606a; }
.badge { display: inline-block; padding: .1rem .45rem; border-radius: 999px; font-size: .8rem;
         border: 1px solid #d0d7de; background: #f6f8fa; }
.note { color: #57606a; font-size: .9rem; }
.warn { color: #9a6700; font-weight: 600; }
"""


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


def _table(headers, rows):
    parts = ["<table>", "<thead><tr>"]
    parts.extend("<th>{0}</th>".format(_escape(str(header))) for header in headers)
    parts.append("</tr></thead>")
    parts.append("<tbody>")
    for row in rows:
        parts.append("<tr>")
        parts.extend("<td>{0}</td>".format(cell) for cell in row)
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def _bullets(items):
    return "<ul>" + "".join("<li>{0}</li>".format(item) for item in items) + "</ul>"


def render_html(payload):
    """`opslens.report/1` 载荷 → 单文件 HTML（内联 CSS，零外链）。"""
    digits = payload.get("inputs", {}).get("rate_precision")

    def e(value):
        """数值 → 转义文本（精度取自载荷）。"""
        return _escape(_fmt(value, digits), quote=True)

    def esc(value):
        """纯文本 → 转义文本。"""
        return _escape(value, quote=True)

    summary = payload["summary"]
    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append("<title>opslens 删换建议报告</title>")
    parts.append("<style>{0}</style>".format(_STYLE))
    parts.append("</head>")
    parts.append("<body>")

    parts.append("<h1>opslens 删换建议报告</h1>")
    parts.append(
        '<p class="note">schema：<code>{0}</code>　定位：{1}</p>'.format(
            esc(payload["schema"]), esc(payload["positioning"]["statement"])
        )
    )

    # 摘要
    parts.append("<h2>摘要</h2>")
    parts.append(
        _bullets(
            [
                "server 数：<b>{0}</b>".format(e(summary["servers"])),
                "调用总数：<b>{0}</b>（error {1} / unknown {2}）".format(
                    e(summary["calls_total"]), e(summary["calls_error"]), e(summary["calls_unknown"])
                ),
                "建议条数：<b>{0}</b>（其中\"建议移除\" <b>{1}</b>）".format(
                    e(summary["suggestions"]), e(summary["remove_candidate"])
                ),
                "\"数据不足\"降级条数：<b>{0}</b>".format(e(summary["insufficient_data"])),
                "未生效规则条数：<b>{0}</b>".format(e(summary["ineffective_rules"])),
            ]
        )
    )

    # ① 数据来源与覆盖声明
    declaration = payload["source_declaration"]
    parts.append("<h2>一、数据来源与覆盖声明</h2>")
    parts.append(
        _bullets(
            [
                "扫描根目录：<code>{0}</code>".format(e(declaration.get("home"))),
                "输入 schema：events <code>{0}</code> / aggregate <code>{1}</code> / attribute <code>{2}</code>".format(
                    esc(payload["inputs"]["events_schema"]),
                    esc(payload["inputs"]["aggregate_schema"]),
                    esc(payload["inputs"]["attribute_schema"]),
                ),
            ]
        )
    )
    parts.append(
        _table(
            ["来源文件", "类型"],
            [
                ["<code>{0}</code>".format(esc(item["relative"])), esc(item["kind"])]
                for item in declaration["sources"]
            ]
            or [["（无）", "—"]],
        )
    )
    versions = "；".join(
        "{0} = {1}".format(source, ", ".join(values))
        for source, values in sorted(declaration["schema_versions"].items())
    ) or "（无）"
    parts.append(
        _bullets(
            [
                "schema 版本：{0}".format(esc(versions)),
                esc(declaration["coverage_note"] or ""),
                esc(declaration["totals_note"]),
            ]
        )
    )

    # ② unknown / 样本缺失独立分区
    unknown = payload["unknown_partition"]
    parts.append("<h2>二、{0}</h2>".format(esc(unknown["title"])))
    parts.append('<p class="note">{0}</p>'.format(esc(unknown["note"])))
    parts.append(
        _bullets(
            [
                "unknown 调用：<b>{0}</b> / 总调用 {1}".format(
                    e(unknown["calls_unknown"]), e(unknown["calls_total"])
                ),
                "token 缺失样本：<b>{0}</b>".format(e(unknown["token_missing"])),
                "耗时缺失样本：<b>{0}</b>".format(e(unknown["duration_missing"])),
            ]
        )
    )
    parts.append(
        _table(
            ["source", "server", "总数", "ok", "error", "unknown", "token 缺失", "耗时缺失"],
            [
                [
                    esc(row["source"]),
                    esc(row["server"]),
                    e(row["calls_total"]),
                    e(row["calls_ok"]),
                    e(row["calls_error"]),
                    e(row["calls_unknown"]),
                    e(row["token_missing"]),
                    e(row["duration_missing"]),
                ]
                for row in unknown["by_server"]
            ],
        )
    )
    parts.append("<blockquote>{0}</blockquote>".format(esc(unknown["unattributed"]["note"])))

    # ③ 建议清单
    parts.append("<h2>三、建议清单</h2>")
    if not payload["suggestions"]:
        parts.append("<p>本次统计未触发任何建议（无 server 同时满足失败率与样本量门槛）。</p>")
    for entry in payload["suggestions"]:
        parts.append(
            '<h3><span class="badge">{0}</span> {1}/{2}</h3>'.format(
                esc(entry["type"]), esc(entry["source"]), esc(entry["server"])
            )
        )
        parts.append(
            _bullets(
                [
                    "口径：<code>{0}</code> = <b>{1}</b>".format(esc(entry["metric"]), e(entry["value"])),
                    "分子/分母：<b>{0}</b> / <b>{1}</b>".format(e(entry["numerator"]), e(entry["denominator"])),
                    "样本量：<b>{0}</b>".format(e(entry["sample_size"])),
                    "阈值取值：{0}".format(
                        ", ".join(
                            "{0}={1}".format(esc(key), e(value))
                            for key, value in sorted(entry["threshold"].items())
                        )
                    ),
                    "样本门槛：{0}".format(
                        ", ".join(
                            "{0}={1}".format(esc(key), e(value))
                            for key, value in sorted(entry["sample_requirement"].items())
                        )
                    ),
                    esc(entry["basis"]),
                ]
            )
        )

    parts.append("<h3>数据不足（降级，不出建议）</h3>")
    if not payload["insufficient_data"]:
        parts.append("<p>无。</p>")
    else:
        parts.append(
            _table(
                ["轴", "source", "server", "观测样本", "需要样本", "原因"],
                [
                    [
                        esc(item["axis"]),
                        esc(item["source"]),
                        esc(item["server"]),
                        e(item["observed_sample"]),
                        e(item["required_sample"]),
                        esc(item["reason"]),
                    ]
                    for item in payload["insufficient_data"]
                ],
            )
        )
    ineffective_text = "；".join(
        "{0}（{1}）".format(item["id"], "，".join(item["reasons"]))
        for item in payload["failure_attribution"]["ineffective_rules"]
    ) or "（无）"
    parts.append(
        "<blockquote>未生效规则清单（不参与匹配，其覆盖类别落 <code>other</code>）：{0}</blockquote>".format(
            esc(ineffective_text)
        )
    )

    # ④ 失败模式归因
    attribution = payload["failure_attribution"]
    parts.append("<h2>四、失败模式归因（规则匹配，非 AI 评分）</h2>")
    parts.append(
        "<p>失败调用 {0} 次：命中规则 {1} 次 / 落 other {2} 次。</p>".format(
            e(attribution["calls_error"]), e(attribution["matched"]), e(attribution["other"])
        )
    )
    parts.append(
        _table(
            ["类别", "次数"],
            [[esc(item["category"]), e(item["calls"])] for item in attribution["by_category"]],
        )
    )
    parts.append(
        "<p>生效规则：{0}</p>".format(esc(", ".join(attribution["effective_rule_ids"]) or "（无）"))
    )
    if attribution["ineffective_rules"]:
        parts.append("<p>未生效规则（原因）：</p>")
        parts.append(
            _bullets(
                [
                    "<code>{0}</code>：{1}".format(esc(item["id"]), esc("，".join(item["reasons"])))
                    for item in attribution["ineffective_rules"]
                ]
            )
        )

    # ⑤ 排名
    parts.append("<h2>五、排名（Top 清单）</h2>")
    parts.append('<p class="note">{0}</p>'.format(esc(payload["rankings"]["note"])))
    for title, key in (("失败率 Top", "failure_rate_top"), ("token 开销 Top", "turn_token_top")):
        parts.append("<h3>{0}</h3>".format(esc(title)))
        rows = payload["rankings"][key]
        if not rows:
            parts.append("<p>（无可排名维度）</p>")
            continue
        parts.append(
            _table(
                ["source", "server", "值"],
                [[esc(row["source"]), esc(row["server"]), e(row["value"])] for row in rows],
            )
        )

    # ⑥ 定位宣言
    parts.append("<h2>六、定位与声明</h2>")
    parts.append(
        _bullets(
            [
                esc(payload["positioning"]["statement"]),
                '<span class="warn">{0}</span>'.format(esc(payload["positioning"]["not_auto_modify"])),
            ]
        )
    )

    parts.append("</body>")
    parts.append("</html>")
    return guard.assert_no_external_resources("\n".join(parts) + "\n")
