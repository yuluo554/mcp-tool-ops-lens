"""opslens 命令行入口：argparse + 退出码语义（plan/02 §六）。

骨架期：五个子命令已注册且参数契约锁定，但实现坐标为"阶段未就绪"（exit 3），
绝不伪造空结果——对应模块落地时 exit 3 整项退役。

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
from .config import ConfigError, load_rules

PROG = "opslens"


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


def _not_ready(command):
    """骨架期占位：明确报"阶段未就绪"并给退出码 3，不产出任何假结果。"""
    sys.stderr.write(
        "[{0}] 命令 `{1}` 尚未实现（模块未落地）：按纪律不伪造空结果。\n".format(PROG, command)
    )
    sys.stderr.write("[{0}] 实现计划见 plan/05-里程碑.md 与 plan/03-模块详设.md。\n".format(PROG))
    return exit_codes.EXIT_NOT_READY


def main(argv=None):
    _encoding.ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return exit_codes.EXIT_USAGE

    try:
        # 规则包存在性前置检查：先验证配置可加载，避免"未就绪"掩盖配置缺失。
        if args.command in ("scan", "attribute", "report", "bench"):
            load_rules(args.rules_dir)
        return _not_ready(args.command)
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
