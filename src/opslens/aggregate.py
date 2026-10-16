"""模块 2 · 工具调用统计聚合（确定性 SQL 聚合，**无任何模型参与**）。

口径唯一出处：`plan/03 §2.1`「聚合维度与指标（唯一口径表）」。本模块与 `attribute.py`
是**除法运算（`BinOp(Div)`）的唯二落点**——口径唯一性守门（AST 断言）见
`tests/test_aggregate.py`：`src/` 与 `tools/` 内 `BinOp(Div)` 只允许出现在本模块、
`attribute.py` 与基准生成器 `tools/gen_synthetic_logs.py`。
生成器进白名单的理由：它推导的是**期望值（真值）**，必须与引擎相互独立；
让两者共用一份实现，真值就沦为"引擎自证"（K12 明禁）。

确定性纪律：`sqlite3` 内存库（`:memory:`），同输入同结果；不读时钟、不读随机。
重试窗口与比率精度一律由调用方从 `data/rules/*.json` **注入**（K9：代码零字面量）。

三态纪律（K1）：`unknown` 是第一位公民——两级维度都单列 `calls_unknown`，
且**不进失败率分母**（分母 = `calls_ok + calls_error`）。
"""

import re
import sqlite3

from . import schema

# 聚合载荷的 schema 标识（唯一出处）
AGGREGATE_SCHEMA = "opslens.aggregate/1"

_TABLE = "calls"

# 建表语句：列名与 `plan/03 §2.1` 的指标一一对应（SQL 列名即口径名）
_CREATE_TABLE = """
CREATE TABLE calls (
    source TEXT NOT NULL,
    server TEXT NOT NULL,
    tool TEXT NOT NULL,
    status TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts_seconds INTEGER,
    tokens_present INTEGER NOT NULL,
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_cache_read INTEGER,
    tokens_cache_creation INTEGER,
    duration_ms INTEGER
)
"""

# 两级维度的聚合列（除分组键外完全一致，保证两级口径同源）
_METRIC_SELECT = """
    COUNT(*) AS calls_total,
    SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) AS calls_ok,
    SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS calls_error,
    SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) AS calls_unknown,
    SUM(CASE WHEN tokens_present = 1 THEN tokens_input ELSE 0 END) AS tokens_input,
    SUM(CASE WHEN tokens_present = 1 THEN tokens_output ELSE 0 END) AS tokens_output,
    SUM(CASE WHEN tokens_present = 1 THEN tokens_cache_read ELSE 0 END) AS tokens_cache_read,
    SUM(CASE WHEN tokens_present = 1 THEN tokens_cache_creation ELSE 0 END) AS tokens_cache_creation,
    SUM(tokens_present) AS token_samples,
    SUM(CASE WHEN tokens_present = 0 THEN 1 ELSE 0 END) AS token_missing,
    SUM(CASE WHEN duration_ms IS NOT NULL THEN duration_ms ELSE 0 END) AS duration_sum,
    SUM(CASE WHEN duration_ms IS NOT NULL THEN 1 ELSE 0 END) AS duration_samples,
    SUM(CASE WHEN duration_ms IS NULL THEN 1 ELSE 0 END) AS duration_missing
"""

_SERVER_SQL = (
    "SELECT source, server, " + _METRIC_SELECT + " FROM calls GROUP BY source, server ORDER BY source, server"
)

_TOOL_SQL = (
    "SELECT source, server, tool, "
    + _METRIC_SELECT
    + " FROM calls GROUP BY source, server, tool ORDER BY source, server, tool"
)

# 重试识别（plan/03 §2.1）：同 (source, server, tool) 在**时间窗**内失败后再次调用，记一次重试。
# 窗口值以参数注入（不写死）。按 (ts_seconds, seq) 排序：时间优先，同刻用源行号兜底保证确定性。
_RETRY_SQL = """
SELECT source, server, tool, SUM(is_retry) AS retry_count FROM (
    SELECT
        source, server, tool,
        CASE
            WHEN LAG(status) OVER w = 'error'
             AND ts_seconds IS NOT NULL
             AND LAG(ts_seconds) OVER w IS NOT NULL
             AND (ts_seconds - LAG(ts_seconds) OVER w) <= ?
            THEN 1 ELSE 0
        END AS is_retry
    FROM calls
    WINDOW w AS (PARTITION BY source, server, tool ORDER BY ts_seconds, seq)
)
GROUP BY source, server, tool
ORDER BY source, server, tool
"""

# ISO 时间戳解析：`YYYY-MM-DDTHH:MM:SS[.fff][Z|±HH:MM]`。
# 只做**字符串→秒**的纯整数换算（不 import 时钟/`datetime`），偏移量参与换算，
# 使跨时区日志的窗口差值仍然正确。不可解析 → None（不参与重试判定，不猜）。
_TIMESTAMP_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})T"
    r"(?P<hh>\d{2}):(?P<mm>\d{2}):(?P<ss>\d{2})(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


def timestamp_to_seconds(value):
    """ISO 时间戳字符串 → 自 1970-01-01T00:00:00Z 起的整数秒（不可解析 → None）。

    用纯整数运算（Howard Hinnant 的 civil-from-days 逆算法），不依赖 `datetime`
    也不读系统时钟——确定性纪律要求"全程不读时钟"（plan/02 §四）。
    """
    if not isinstance(value, str):
        return None
    match = _TIMESTAMP_RE.match(value.strip())
    if not match:
        return None
    year = int(match.group("y"))
    month = int(match.group("m"))
    day = int(match.group("d"))
    hour = int(match.group("hh"))
    minute = int(match.group("mm"))
    second = int(match.group("ss"))
    days = _days_from_civil(year, month, day)
    total = days * 86400 + hour * 3600 + minute * 60 + second
    tz = match.group("tz")
    if tz and tz != "Z":
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        total -= sign * (int(digits[:2]) * 3600 + int(digits[2:4]) * 60)
    return total


def _days_from_civil(year, month, day):
    """公历 → 自 1970-01-01 起的天数（纯整数，闰年规则完整）。"""
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    year_of_era = year - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def _build_connection(events):
    """建内存库并灌入 IR 事件流。"""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(_CREATE_TABLE)
    rows = []
    for event in events:
        tokens = event.tokens
        present = 1 if tokens is not None else 0
        if tokens is None:
            values = (None, None, None, None)
        else:
            values = (tokens.input, tokens.output, tokens.cache_read, tokens.cache_creation)
        rows.append(
            (
                event.source,
                event.server,
                event.tool,
                event.status,
                event.seq,
                timestamp_to_seconds(event.timestamp),
                present,
                values[0],
                values[1],
                values[2],
                values[3],
                event.duration_ms,
            )
        )
    connection.executemany(
        "INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    return connection


def _round_ratio(numerator, denominator, precision):
    """比率 = 分子 / 分母（**本项目的除法落点之一**）。

    分母为 0 → `None`（不是 0，也不是 1）——"无样本"与"零失败"必须可区分。
    """
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), precision)


def _finish_row(row, precision, retry_count, level):
    """SQL 聚合行 → 指标行（比率/均值在此计算，SQL 只出计数与求和）。"""
    calls_total = row["calls_total"]
    calls_ok = row["calls_ok"]
    calls_error = row["calls_error"]
    calls_unknown = row["calls_unknown"]

    # 对账等式（plan/03 §2.1）：三态之和 == 总数；不成立即内部错误，绝不静默出数
    if calls_ok + calls_error + calls_unknown != calls_total:
        raise AssertionError(
            "对账等式被打破：{0} + {1} + {2} != {3}".format(calls_ok, calls_error, calls_unknown, calls_total)
        )

    denominator = calls_ok + calls_error  # unknown 不进分母（K1）
    token_samples = row["token_samples"] or 0
    token_missing = row["token_missing"] or 0
    duration_samples = row["duration_samples"] or 0
    duration_missing = row["duration_missing"] or 0

    if token_samples:
        token_values = (
            row["tokens_input"],
            row["tokens_output"],
            row["tokens_cache_read"],
            row["tokens_cache_creation"],
        )
        token_sum = sum(token_values)
    else:
        # 无样本 → 四项一律 null（缺失 ≠ 0，K2）；用 token_samples/token_missing 表达样本量
        token_values = (None, None, None, None)
        token_sum = None

    result = {
        "level": level,
        "source": row["source"],
        "server": row["server"],
        "calls_total": calls_total,
        "calls_ok": calls_ok,
        "calls_error": calls_error,
        "calls_unknown": calls_unknown,
        "failure_rate": _round_ratio(calls_error, denominator, precision),
        "failure_rate_numerator": calls_error,
        "failure_rate_denominator": denominator,
        "insufficient_data": denominator == 0,
        "retry_count": retry_count,
        "tokens_input": token_values[0],
        "tokens_output": token_values[1],
        "tokens_cache_read": token_values[2],
        "tokens_cache_creation": token_values[3],
        "token_samples": token_samples,
        "token_missing": token_missing,
        "turn_token_avg": _round_ratio(token_sum, token_samples, precision),
        "duration_avg_ms": _round_ratio(row["duration_sum"], duration_samples, precision),
        "duration_samples": duration_samples,
        "duration_missing": duration_missing,
        # Claude 侧按工具耗时不可得（K4）：样本数为 0 → 显式 false，绝不用 0 冒充
        "duration_available": duration_samples > 0,
    }
    if level == "tool":
        result["tool"] = row["tool"]
    return result


def _query(connection, sql, params=()):
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def aggregate(events, rules):
    """事件流 → 两级聚合载荷（`plan/03 §2.1` 指标逐项）。

    返回 `opslens.aggregate/1` 载荷：`server_level`（`GROUP BY source, server`）与
    `tool_level`（`GROUP BY source, server, tool`）**两级都单列 `calls_unknown`**
    ——"未声明"不得看起来像"没问题"（plan/03 §2.2）。
    """
    window_seconds = int((rules.params.get("retry") or {})["window_seconds"])
    precision = int(rules.params["rate_precision"])

    connection = _build_connection(events)
    try:
        server_rows = _query(connection, _SERVER_SQL)
        tool_rows = _query(connection, _TOOL_SQL)
        retry_rows = _query(connection, _RETRY_SQL, (window_seconds,))
    finally:
        connection.close()

    retry_by_tool = dict(
        ((row["source"], row["server"], row["tool"]), row["retry_count"]) for row in retry_rows
    )
    retry_by_server = {}
    for key, value in retry_by_tool.items():
        server_key = (key[0], key[1])
        retry_by_server[server_key] = retry_by_server.get(server_key, 0) + value

    server_level = [
        _finish_row(row, precision, retry_by_server.get((row["source"], row["server"]), 0), "server")
        for row in server_rows
    ]
    tool_level = [
        _finish_row(
            row,
            precision,
            retry_by_tool.get((row["source"], row["server"], row["tool"]), 0),
            "tool",
        )
        for row in tool_rows
    ]

    return {
        "schema": AGGREGATE_SCHEMA,
        "rate_precision": precision,
        "retry_window_seconds": window_seconds,
        "server_level": server_level,
        "tool_level": tool_level,
        "totals": _totals(server_level, precision),
        "coverage_note": (
            "聚合口径见 plan/03 §2.1；失败率分母不含 unknown；token 四项分列且按调用轮次归属"
            "（Codex 侧不按工具归因，token_samples=0 表示该维度不可得而非零开销）；"
            "Claude 侧按工具耗时不可得（duration_available=false）。"
        ),
    }


def _totals(server_level, precision):
    """全量汇总（与 server 级同口径，防"汇总另算一份"）。"""
    calls_total = sum(row["calls_total"] for row in server_level)
    calls_ok = sum(row["calls_ok"] for row in server_level)
    calls_error = sum(row["calls_error"] for row in server_level)
    calls_unknown = sum(row["calls_unknown"] for row in server_level)
    denominator = calls_ok + calls_error
    return {
        "calls_total": calls_total,
        "calls_ok": calls_ok,
        "calls_error": calls_error,
        "calls_unknown": calls_unknown,
        "failure_rate": _round_ratio(calls_error, denominator, precision),
        "failure_rate_numerator": calls_error,
        "failure_rate_denominator": denominator,
        "retry_count": sum(row["retry_count"] for row in server_level),
        "token_samples": sum(row["token_samples"] for row in server_level),
        "token_missing": sum(row["token_missing"] for row in server_level),
        "duration_samples": sum(row["duration_samples"] for row in server_level),
        "servers": len(server_level),
    }
