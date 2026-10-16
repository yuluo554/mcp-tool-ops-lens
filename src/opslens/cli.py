"""opslens 命令行入口：argparse + 退出码语义（plan/02 §六）。

M2 起 `scan` 已接通解析层（模块 1）；M3 起 `aggregate` / `attribute` 接通聚合层与归因层
（模块 2/3）。尚未落地的子命令（`report` / `bench`）**明确报"本构建尚未包含"并以用法码（2）
退出**，绝不伪造空结果——骨架期的退出码 `3`（阶段未就绪）已随 M2 整项退役。

用法：
    opslens scan      --home <目录> [--out events.json] [--rules-dir <目录>]
    opslens aggregate --events events.json [--out agg.json]
    opslens attribute --events events.json [--out attr.json]
    opslens report    --events events.json --out <目录>
    opslens bench     [--only <套件名>] [--check]
"""

import argparse
import os
import sys

from . import __version__
from . import _encoding
from . import exit_codes
from . import pipeline
from . import serialize
from .config import ConfigError, load_rules

PROG = "opslens"

# 已接通的子命令（其余为"本构建尚未包含"）
IMPLEMENTED_COMMANDS = ("scan", "aggregate", "attribute")

# 需要规则包的子命令（口径参数以参数注入解析层/聚合层，保持两层纯函数）
_RULES_COMMANDS = ("scan", "aggregate", "attribute", "report", "bench")


def build_parser():
    """构造参数解析器。测试用反射校对 README 与 CLI 一致性，勿改函数名。"""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="MCP/工具调用失败率与上下文开销归因（纯本地、零上传）",
    )
    parser.add_argument("--version", action="version", version="{0} {1}".format(PROG, __version__))
    subparsers = parser.add_subparsers(dest="command", metavar="<命令>")

    scan = subparsers.add_parser("scan", help="解析本机/指定目录的会话日志为统一事件流")
    scan.add_argument("--home", default=None, help="数据源根目录；缺省为当前用户 home（测试请显式传临时目录）")
    scan.add_argument("--out", default=None, help="事件流输出路径（JSON）")
    _add_rules_dir(scan)

    aggregate = subparsers.add_parser("aggregate", help="按 server / tool 两级聚合调用统计")
    aggregate.add_argument("--events", required=True, help="scan 产出的事件流 JSON")
    aggregate.add_argument("--out", default=None, help="聚合结果输出路径（JSON）")
    _add_rules_dir(aggregate)

    attribute = subparsers.add_parser("attribute", help="对失败调用做规则匹配分类")
    attribute.add_argument("--events", required=True, help="scan 产出的事件流 JSON")
    attribute.add_argument("--out", default=None, help="归因结果输出路径（JSON）")
    _add_rules_dir(attribute)

    report = subparsers.add_parser("report", help="产出删换建议报告（Markdown + HTML + JSON）")
    report.add_argument("--events", required=True, help="scan 产出的事件流 JSON")
    report.add_argument("--out", required=True, help="报告输出目录")
    _add_rules_dir(report)

    bench = subparsers.add_parser("bench", help="真值基准：引擎输出 vs 植入真值对账")
    bench.add_argument("--only", default=None, help="只跑指定套件")
    bench.add_argument("--check", action="store_true", help="只校验冻结产物位级一致，不重跑")
    _add_rules_dir(bench)

    return parser


def _add_rules_dir(sub):
    sub.add_argument("--rules-dir", default=None, help="规则包目录；缺省用 data/rules")


def _not_in_this_build(command):
    """尚未落地的子命令：明确报"本构建尚未包含"，绝不伪造空结果。"""
    sys.stderr.write(
        "[{0}] 命令 `{1}` 本构建尚未包含（模块未落地）：按纪律不伪造空结果。\n".format(PROG, command)
    )
    sys.stderr.write("[{0}] 实现计划见 plan/05-里程碑.md 与 plan/03-模块详设.md。\n".format(PROG))
    return exit_codes.EXIT_USAGE


def _read_events(path):
    """读入 `scan` 产出的事件流（缺文件 / 结构非法 → 数据不可用，exit 4）。"""
    if not os.path.isfile(path):
        raise exit_codes.DataUnavailableError("事件流文件不存在：{0}".format(path))
    try:
        payload = serialize.read_json(path)
    except ValueError as exc:
        raise exit_codes.DataUnavailableError("事件流不是合法 JSON：{0}（{1}）".format(path, exc))
    return pipeline.events_from_payload(payload)


def _run_aggregate(args, rules):
    events = _read_events(args.events)
    if not events:
        raise exit_codes.DataUnavailableError("事件流为空：{0}".format(args.events))
    payload = pipeline.aggregate_events(events, rules)

    if args.out:
        serialize.write_json(args.out, payload)

    totals = payload["totals"]
    sys.stdout.write(
        "[{0}] 聚合完成：{1} 次调用（ok={2} error={3} unknown={4}）/ {5} 个 server\n".format(
            PROG,
            totals["calls_total"],
            totals["calls_ok"],
            totals["calls_error"],
            totals["calls_unknown"],
            totals["servers"],
        )
    )
    for row in payload["server_level"]:
        rate = "n/a" if row["failure_rate"] is None else "{0:.6f}".format(row["failure_rate"])
        sys.stdout.write(
            "  - {0}/{1}：失败率 {2}（{3}/{4}） unknown={5} 重试={6}\n".format(
                row["source"],
                row["server"],
                rate,
                row["failure_rate_numerator"],
                row["failure_rate_denominator"],
                row["calls_unknown"],
                row["retry_count"],
            )
        )
    if args.out:
        sys.stdout.write("  - 聚合结果已写出：{0}\n".format(args.out))
    return exit_codes.EXIT_OK


def _run_attribute(args, rules):
    events = _read_events(args.events)
    if not events:
        raise exit_codes.DataUnavailableError("事件流为空：{0}".format(args.events))
    payload = pipeline.attribute_events(events, rules)

    if args.out:
        serialize.write_json(args.out, payload)

    totals = payload["totals"]
    sys.stdout.write(
        "[{0}] 归因完成：{1} 次失败调用（命中 {2} / 落 other {3}）\n".format(
            PROG, totals["calls_error"], totals["matched"], totals["other"]
        )
    )
    for item in payload["by_category"]:
        sys.stdout.write("  - {0}：{1}\n".format(item["category"], item["calls"]))
    if payload["ineffective_rules"]:
        sys.stderr.write("[{0}] 未生效规则 {1} 条（未进计算路径，原因已登记在产物）：\n".format(PROG, len(payload["ineffective_rules"])))
        for item in payload["ineffective_rules"]:
            sys.stderr.write("  - {0}：{1}\n".format(item["id"], "；".join(item["reasons"])))
    if args.out:
        sys.stdout.write("  - 归因结果已写出：{0}\n".format(args.out))
    return exit_codes.EXIT_OK


def _default_home():
    return os.path.expanduser("~")


def _run_scan(args, rules):
    home = args.home or _default_home()
    max_error_chars = (rules.params.get("error_text") or {}).get("max_chars")
    events, report = pipeline.scan_home(home, max_error_chars)

    if args.out:
        payload = pipeline.build_events_payload(events, report)
        serialize.write_json(args.out, payload)

    counts = {"ok": 0, "error": 0, "unknown": 0}
    for event in events:
        counts[event.status] += 1
    sys.stdout.write(
        "[{0}] 解析完成：{1} 个文件 / {2} 次工具调用"
        "（ok={3} error={4} unknown={5}）\n".format(
            PROG, len(report["sources"]), len(events), counts["ok"], counts["error"], counts["unknown"]
        )
    )
    for source, versions in sorted(report["schema_versions"].items()):
        sys.stdout.write("  - {0} schema 版本：{1}\n".format(source, ", ".join(versions)))
    if args.out:
        sys.stdout.write("  - 事件流已写出：{0}\n".format(args.out))
    if report["skipped"]:
        sys.stderr.write(
            "[{0}] 跳过 {1} 个无法判别的日志文件（已登记在产物 report.skipped）\n".format(
                PROG, len(report["skipped"])
            )
        )
    if report["diagnostics"]:
        sys.stderr.write(
            "[{0}] 注记 {1} 条次生信号（已登记在产物 report.diagnostics）\n".format(
                PROG, len(report["diagnostics"])
            )
        )
    return exit_codes.EXIT_OK


def main(argv=None):
    _encoding.ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return exit_codes.EXIT_USAGE

    try:
        # 规则包存在性前置检查：先验证配置可加载，避免"未实现"掩盖配置缺失。
        rules = None
        if args.command in _RULES_COMMANDS:
            rules = load_rules(args.rules_dir)
        if args.command == "scan":
            return _run_scan(args, rules)
        if args.command == "aggregate":
            return _run_aggregate(args, rules)
        if args.command == "attribute":
            return _run_attribute(args, rules)
        return _not_in_this_build(args.command)
    except ConfigError as exc:
        sys.stderr.write("[{0}] 规则包错误：{1}\n".format(PROG, exc))
        return exit_codes.EXIT_DATA_UNAVAILABLE
    except exit_codes.OpsLensError as exc:
        sys.stderr.write("[{0}] {1}\n".format(PROG, exc.message))
        return exc.exit_code
    except KeyboardInterrupt:
        sys.stderr.write("[{0}] 已中断\n".format(PROG))
        return exit_codes.EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
