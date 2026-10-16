#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""合成日志生成器（M1 数据先行）。规格见 plan/04 §三、plan/03 §5.1。

纪律（均有守门测试）：
  · 自研 splitmix64 确定性 RNG；禁 stdlib `random` / 禁 `set` 迭代序 / 禁系统时钟。
  · server 名一律 `fake-*` 白名单；真实 server 名进禁止词表（tests/test_privacy.py）。
  · 产物无"生成时间"字段；日志内的事件时间是固定常量 + 整数偏移推导，不读时钟。
  · `truth.json` 只存"输入与期望"，**不得**出现 `observed_*` / `engine_output` 一类字段。
  · 写盘一律经 `opslens.serialize`（确定性写盘唯一入口）。
  · `--check`：重新生成并与盘中比对，逐字节一致。

用法：
    py -X utf8 tools/gen_synthetic_logs.py --out data/synthetic
    py -X utf8 tools/gen_synthetic_logs.py --check
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
if os.path.join(_REPO_ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from opslens import _encoding  # noqa: E402
from opslens import config  # noqa: E402
from opslens import exit_codes  # noqa: E402
from opslens import serialize  # noqa: E402

DEFAULT_SEED = 20261016
DEFAULT_OUT = os.path.join("data", "synthetic")
DEFAULT_RULES_DIR = os.path.join(_REPO_ROOT, "data", "rules")

CLAUDE_LOG = "logs/claude_alpha.jsonl"
CODEX_LOG = "logs/codex_alpha.jsonl"
TRUTH_FILE = "truth.json"
MANIFEST_FILE = "manifest.json"

CLAUDE_SOURCE_VERSION = "2.1.233"
CODEX_CLI_VERSION = "0.146.0-alpha.3.1"

# 事件时间的固定推导基点（常量，不是时钟读数）：2026-10-16T00:00:00Z
_TS_BASE_DATE = "2026-10-16"

# 合成数据用的路径占位（绝不写本机真实路径）
_REDACTED_PATH = "<redacted-path>"

# ---------------------------------------------------------------------------
# 自研确定性 RNG：splitmix64
# ---------------------------------------------------------------------------

_MASK64 = (1 << 64) - 1
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15


class SplitMix64(object):
    """splitmix64：同 seed 同序列，与平台/Python 版本无关。"""

    def __init__(self, seed):
        self._state = seed & _MASK64

    def next_u64(self):
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        return (z ^ (z >> 31)) & _MASK64

    def below(self, bound):
        """[0, bound) 上的整数；用取模而非浮点，跨平台稳定。"""
        if bound <= 0:
            raise ValueError("bound must be positive")
        return self.next_u64() % bound

    def between(self, low, high):
        """闭区间 [low, high]。"""
        return low + self.below(high - low + 1)

    def shuffle(self, items):
        """确定性 Fisher-Yates（降序），不依赖任何哈希/集合迭代序。"""
        for index in range(len(items) - 1, 0, -1):
            swap = self.below(index + 1)
            items[index], items[swap] = items[swap], items[index]
        return items


# ---------------------------------------------------------------------------
# 时间字符串：由整数偏移推导，不读时钟、不用 datetime
# ---------------------------------------------------------------------------


def iso_timestamp(offset_seconds, offset_millis):
    hours = offset_seconds // 3600
    minutes = (offset_seconds % 3600) // 60
    seconds = offset_seconds % 60
    return "{0}T{1:02d}:{2:02d}:{3:02d}.{4:03d}Z".format(
        _TS_BASE_DATE, hours, minutes, seconds, offset_millis
    )


# ---------------------------------------------------------------------------
# 失败模式文本（与 data/rules/failure_patterns.json 的模式表对应；
# 内容为合成构造，不含本机真实路径与个人信息）
# ---------------------------------------------------------------------------

MODE_TEXTS = {
    "timeout": [
        "Exit code 143\nCommand timed out after 10m 0s",
        "ETIMEDOUT: request to upstream timed out",
    ],
    "permission_denied": [
        "PermissionError: [Errno 13] Permission denied: '{0}'".format(_REDACTED_PATH),
        "listing failed with error: 0x80070005\nAccess is denied.",
    ],
    "invalid_args": [
        "SyntaxError: invalid syntax",
        "AttributeError: module 'sample_lib' has no attribute 'render'",
        "error: unexpected argument '-n' found",
    ],
    "content_refusal": [
        "I cannot assist with that request.",
        "Unable to comply with this instruction.",
    ],
    "other": [
        "Tool execution aborted before completion.",
        "Upstream returned an unrecognized payload shape.",
    ],
}

# 每个 server 的植入规格。calls = ok + error + unknown（生成时自校验）。
SERVER_SPECS = [
    {
        "server": "fake-high-fail",
        "shape": "high",
        "tools": ["tool_exec", "tool_fetch"],
        "calls": 40,
        "ok": 16,
        "error": 24,
        "unknown": 0,
        "modes": {"timeout": 12, "invalid_args": 12},
        "token_scale": "heavy",
    },
    {
        "server": "fake-mid-fail",
        "shape": "mid",
        "tools": ["tool_query", "tool_index"],
        "calls": 40,
        "ok": 26,
        "error": 10,
        "unknown": 4,
        "modes": {"permission_denied": 6, "timeout": 3, "other": 1},
        "token_scale": "normal",
        # 缺失 is_error 的样本中，部分带错误文本（本机实测占 14.9%）
        "unknown_with_error_text": 1,
    },
    {
        "server": "fake-low-fail",
        "shape": "low",
        "tools": ["tool_scan"],
        "calls": 24,
        "ok": 23,
        "error": 1,
        "unknown": 0,
        "modes": {"content_refusal": 1},
        "token_scale": "light",
    },
    {
        "server": "fake-retry",
        "shape": "retry",
        "tools": ["tool_sync"],
        "calls": 30,
        "ok": 22,
        "error": 8,
        "unknown": 0,
        "modes": {"timeout": 8},
        "token_scale": "normal",
        "retry": True,
    },
    {
        "server": "fake-threshold-exact",
        "shape": "threshold_exact",
        "tools": ["tool_check"],
        "calls": 20,
        "ok": 10,
        "error": 10,
        "unknown": 0,
        "modes": {"invalid_args": 10},
        "token_scale": "normal",
    },
    {
        "server": "fake-near-miss",
        "shape": "near_miss",
        "tools": ["tool_probe"],
        "calls": 40,
        "ok": 21,
        "error": 19,
        "unknown": 0,
        "modes": {"permission_denied": 19},
        "token_scale": "normal",
    },
]

TOKEN_RANGES = {
    "heavy": {"input": (40000, 60000), "output": (800, 2200), "cache_read": (8000, 24000)},
    "normal": {"input": (8000, 20000), "output": (200, 900), "cache_read": (1000, 6000)},
    "light": {"input": (1500, 4000), "output": (60, 260), "cache_read": (0, 400)},
}

# 调用节奏（合成数据的**设计常数**，不是引擎阈值）。
# **M3 复核发现并修正的 M1 缺陷**：旧实现所有调用一律间隔 3 秒，于是"失败后窗口内再次调用"
# 这个重试口径对**每个** server 都成立（实测 24/10/1/8/10/18），而 truth 声明的期望是
# "只有重试型 server 有 8 次重试，其余为 0"——期望值不可由日志推导（真值沦为植入断言）。
# 修正：重试型 server 的调用间隔落在窗口**内**，其余 server 落在窗口**外**，
# 使窗口规则能把两者区分开（与 truth 的声明一致，见 _validate_retry_separation）。
_RETRY_CALL_STEP_SECONDS = 3
_DEFAULT_CALL_STEP_SECONDS = 200

# Codex 侧规格：成败只能靠 `Exit code:` 文本模式（data/README §五 D）
CODEX_CALLS = [
    {"tool": "exec", "kind": "function_call", "mode": None, "exit_code": 0, "wall": "0.5"},
    {"tool": "shell_command", "kind": "function_call", "mode": None, "exit_code": 0, "wall": "1.2"},
    {"tool": "exec", "kind": "function_call", "mode": "other", "exit_code": 1, "wall": "0.4"},
    {"tool": "exec", "kind": "function_call", "mode": "timeout", "exit_code": 124, "wall": "20.1"},
    {"tool": "apply_patch", "kind": "custom_tool_call", "mode": None, "exit_code": 0, "wall": "0.2"},
    {"tool": "view_image", "kind": "custom_tool_call", "mode": None, "exit_code": None, "wall": None},
    {"tool": "exec", "kind": "function_call", "mode": "other", "exit_code": 1, "wall": "3.0"},
    {"tool": "exec", "kind": "function_call", "mode": None, "exit_code": 0, "wall": "0.9"},
]


# ---------------------------------------------------------------------------
# 期望值推导（读 data/rules/thresholds.json，不在代码里写阈值字面量）
# ---------------------------------------------------------------------------


def _round_rate(numerator, denominator, precision):
    if denominator == 0:
        return None
    return round(float(numerator) / float(denominator), precision)


def expected_failure_rate(ok, error, precision):
    """failure_rate 分母不含 unknown（K1）。分母为 0 → None。"""
    return _round_rate(error, ok + error, precision)


def expected_suggestion(calls_total, ok, error, thresholds, precision):
    """按 thresholds.json 推出期望建议标签（与模块 4 的触发口径同源）。"""
    min_calls = thresholds["min_samples"]["calls_total_gte"]
    remove = thresholds["remove_candidate"]
    investigate = thresholds["investigate"]
    if calls_total < min_calls:
        return "low_signal"
    rate = expected_failure_rate(ok, error, precision)
    if rate is None:
        return "low_signal"
    if rate >= remove["failure_rate_gte"]:
        return "remove_candidate"
    if rate >= investigate["failure_rate_gte"] and rate < investigate["failure_rate_lt"]:
        return "investigate"
    return "none"


# ---------------------------------------------------------------------------
# Claude 形态合成日志
# ---------------------------------------------------------------------------


def _usage_for(rng, scale):
    band = TOKEN_RANGES[scale]
    return {
        "input_tokens": rng.between(*band["input"]),
        "output_tokens": rng.between(*band["output"]),
        "cache_read_input_tokens": rng.between(*band["cache_read"]),
        "cache_creation_input_tokens": rng.between(0, 1200),
    }


def _build_claude_events(rng):
    """产出 (server, session_id, [ (assistant_line, user_line) ]) 的有序列表。"""
    sessions = []
    for spec in SERVER_SPECS:
        server = spec["server"]
        session_id = "sess-claude-{0}".format(spec["shape"])
        tools = spec["tools"]

        if spec.get("retry"):
            slots = []
            for _ in range(spec["error"]):
                slots.append(("error", "timeout"))
                slots.append(("ok", None))
            for _ in range(spec["ok"] - spec["error"]):
                slots.append(("ok", None))
        else:
            slots = []
            for mode in spec["modes"]:  # dict 保序（3.7+），不用 set
                for _ in range(spec["modes"][mode]):
                    slots.append(("error", mode))
            for _ in range(spec["ok"]):
                slots.append(("ok", None))
            for _ in range(spec["unknown"]):
                slots.append(("unknown", None))
            rng.shuffle(slots)

        pairs = []
        for index, (status, mode) in enumerate(slots):
            tool = tools[index % len(tools)]
            pairs.append((status, mode, tool))
        sessions.append((server, session_id, pairs))
    return sessions


def render_claude_log(rng):
    """渲染 claude_alpha.jsonl 的全部行。"""
    lines = []
    offset = 0
    unknown_seen = {}
    for server, session_id, pairs in _build_claude_events(rng):
        # 调用节奏：重试型 server 的间隔落在重试窗口内，其余落在窗口外
        # （使 truth 的 expected_retry_count 可由日志按窗口规则复算，见 _validate_retry_separation）
        step = _RETRY_CALL_STEP_SECONDS if _is_retry_server(server) else _DEFAULT_CALL_STEP_SECONDS
        lines.append(
            {
                "type": "system",
                "subtype": "init",
                "version": CLAUDE_SOURCE_VERSION,
                "session_id": session_id,
                "timestamp": iso_timestamp(offset, 0),
            }
        )
        offset += 1
        for call_index, (status, mode, tool) in enumerate(pairs):
            call_id = "call_{0}_{1:03d}".format(session_id, call_index)
            assistant_uuid = "asst_{0}_{1:03d}".format(session_id, call_index)
            user_uuid = "user_{0}_{1:03d}".format(session_id, call_index)
            # 同一轮内 assistant 与 user 消息共享同一时刻基准，调用间按 step 推进
            call_offset = offset
            offset += step
            assistant_ts = iso_timestamp(call_offset, 100 + (call_index % 500))
            user_ts = iso_timestamp(call_offset, 400 + (call_index % 500))

            lines.append(
                {
                    "type": "assistant",
                    "uuid": assistant_uuid,
                    "parentUuid": user_uuid,
                    "sessionId": session_id,
                    "session_id": session_id,
                    "timestamp": assistant_ts,
                    "version": CLAUDE_SOURCE_VERSION,
                    "cwd": _REDACTED_PATH,
                    "userType": "external",
                    "isSidechain": False,
                    "message": {
                        "id": "msg_{0}_{1:03d}".format(session_id, call_index),
                        "type": "message",
                        "role": "assistant",
                        "model": "synthetic-model",
                        "stop_reason": "tool_use",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": call_id,
                                "name": "mcp__{0}__{1}".format(server, tool),
                                "input": {"arg": "synthetic"},
                            }
                        ],
                        "usage": _usage_for(rng, _scale_for(server)),
                    },
                }
            )

            result = {
                "type": "tool_result",
                "tool_use_id": call_id,
                "content": "",
            }
            tool_use_result = {"stdout": "", "stderr": "", "interrupted": False}
            if status == "ok":
                result["is_error"] = False
                result["content"] = "ok"
                tool_use_result["stdout"] = "ok"
            elif status == "error":
                result["is_error"] = True
                text = MODE_TEXTS[mode][call_index % len(MODE_TEXTS[mode])]
                result["content"] = text
                tool_use_result["stderr"] = text
            else:
                # 三态之第三态：字段缺失（绝不写 false）——缺失不等于成功。
                # 本机实测：缺失样本中约 14.9% 含错误文本；此处按每个 server 的
                # unknown_with_error_text 配额，取该 server 前 N 条 unknown 样本植入。
                seen = unknown_seen.get(server, 0)
                unknown_seen[server] = seen + 1
                if seen < _unknown_quota(server):
                    text = MODE_TEXTS["other"][0]
                    result["content"] = text
                    tool_use_result["stderr"] = text
                else:
                    result["content"] = "no status declared"

            lines.append(
                {
                    "type": "user",
                    "uuid": user_uuid,
                    "parentUuid": assistant_uuid,
                    "sessionId": session_id,
                    "session_id": session_id,
                    "timestamp": user_ts,
                    "version": CLAUDE_SOURCE_VERSION,
                    "cwd": _REDACTED_PATH,
                    "userType": "external",
                    "isSidechain": False,
                    "message": {"role": "user", "content": [result]},
                    "toolUseResult": tool_use_result,
                }
            )
    return lines


def _scale_for(server):
    for spec in SERVER_SPECS:
        if spec["server"] == server:
            return spec["token_scale"]
    raise KeyError(server)


def _is_retry_server(server):
    for spec in SERVER_SPECS:
        if spec["server"] == server:
            return bool(spec.get("retry"))
    return False


def _call_step_for(server):
    return _RETRY_CALL_STEP_SECONDS if _is_retry_server(server) else _DEFAULT_CALL_STEP_SECONDS


def _count_retries(pairs, step_seconds, window_seconds):
    """按聚合层的重试口径（plan/03 §2.1）在同一 server 的调用序列上实算重试次数。

    口径：同 server + 同 tool 在窗口内失败后再次调用，记一次重试。
    本函数与 `opslens.aggregate` 的 SQL 实现**相互独立**（生成器不得 import 引擎聚合层，
    否则真值变成"引擎自证"，K12）。此处只用于让 truth 的 `expected_retry_count`
    成为**可由输入推导的期望**，而非植入断言。
    """
    last_status = {}
    last_seconds = {}
    count = 0
    for index, (status, _mode, tool) in enumerate(pairs):
        seconds = index * step_seconds
        if (
            last_status.get(tool) == "error"
            and tool in last_seconds
            and (seconds - last_seconds[tool]) <= window_seconds
        ):
            count += 1
        last_status[tool] = status
        last_seconds[tool] = seconds
    return count


def _expected_retry_count(server, pairs, window_seconds):
    """该 server 的期望重试次数（由调用序列 + 节奏常数推导，可复算）。"""
    return _count_retries(pairs, _call_step_for(server), window_seconds)


def _validate_retry_separation(rules):
    """自校验：truth 声明的重试期望必须能由**实际生成的调用序列**按窗口规则复算。

    这是 M3 复核补上的守门：旧数据里"每个 server 都在窗口内再调用"，
    使期望值与日志不可对账（真值沦为植入断言）。
    用与渲染完全相同的 seed 重建序列，故校验打在真实数据上（不是平行实现）。
    """
    window = int(rules.params["retry"]["window_seconds"])
    problems = []
    for server, _session_id, pairs in _build_claude_events(SplitMix64(DEFAULT_SEED)):
        declared = next(spec["error"] if spec.get("retry") else 0 for spec in SERVER_SPECS if spec["server"] == server)
        actual = _expected_retry_count(server, pairs, window)
        if actual != declared:
            problems.append(
                "{0}: 窗口规则实算 {1} 次重试，与声明 {2} 不符".format(server, actual, declared)
            )
    if problems:
        raise SystemExit("[gen] 重试口径自校验失败：{0}".format("; ".join(problems)))


def _unknown_quota(server):
    for spec in SERVER_SPECS:
        if spec["server"] == server:
            return spec.get("unknown_with_error_text", 0)
    return 0


# ---------------------------------------------------------------------------
# Codex 形态合成日志
# ---------------------------------------------------------------------------


def render_codex_log(rng):
    """渲染 codex_alpha.jsonl：session_meta + response_item + event_msg。"""
    session_id = "sess-codex-alpha"
    lines = [
        {
            "type": "session_meta",
            "ordinal": 0,
            "timestamp": iso_timestamp(0, 0),
            "payload": {
                "id": session_id,
                "session_id": session_id,
                "timestamp": iso_timestamp(0, 0),
                "cli_version": CODEX_CLI_VERSION,
                "cwd": _REDACTED_PATH,
                "originator": "synthetic",
                "model_provider": "synthetic",
                "source": "cli",
                "thread_source": "user",
                "context_window": 272000,
                "history_mode": "full",
            },
        },
        {
            "type": "event_msg",
            "ordinal": 1,
            "timestamp": iso_timestamp(0, 100),
            "payload": {"type": "task_started"},
        },
    ]

    ordinal = 2
    offset = 1
    total_usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }

    for index, spec in enumerate(CODEX_CALLS):
        call_id = "call_codex_{0:03d}".format(index)
        kind = spec["kind"]
        offset += 2
        lines.append(
            {
                "type": "response_item",
                "ordinal": ordinal,
                "timestamp": iso_timestamp(offset, 200),
                "payload": {
                    "type": kind,
                    "id": "item_codex_{0:03d}".format(index),
                    "call_id": call_id,
                    "name": spec["tool"],
                    "arguments": "{\"arg\":\"synthetic\"}",
                    "input": "{\"arg\":\"synthetic\"}",
                    "status": "completed",
                },
            }
        )
        ordinal += 1

        output = _codex_output_text(spec)
        offset += 2
        lines.append(
            {
                "type": "response_item",
                "ordinal": ordinal,
                "timestamp": iso_timestamp(offset, 700),
                "payload": {
                    "type": kind + "_output",
                    "id": "out_codex_{0:03d}".format(index),
                    "call_id": call_id,
                    "output": output,
                },
            }
        )
        ordinal += 1

        # 会话级 token（不摊到单次工具调用，K3）
        last_usage = {
            "input_tokens": rng.between(4000, 12000),
            "cached_input_tokens": rng.between(0, 3000),
            "cache_write_input_tokens": 0,
            "output_tokens": rng.between(80, 400),
            "reasoning_output_tokens": rng.between(0, 120),
        }
        last_usage["total_tokens"] = (
            last_usage["input_tokens"] + last_usage["output_tokens"] + last_usage["reasoning_output_tokens"]
        )
        for key in sorted(total_usage):
            total_usage[key] += last_usage[key]
        offset += 1
        lines.append(
            {
                "type": "event_msg",
                "ordinal": ordinal,
                "timestamp": iso_timestamp(offset, 900),
                "payload": {
                    "type": "token_count",
                    "info": {
                        "last_token_usage": last_usage,
                        "total_token_usage": dict(total_usage),
                        "model_context_window": 272000,
                    },
                },
            }
        )
        ordinal += 1

    offset += 1
    lines.append(
        {
            "type": "event_msg",
            "ordinal": ordinal,
            "timestamp": iso_timestamp(offset, 0),
            "payload": {"type": "task_complete"},
        }
    )
    return lines


def _codex_output_text(spec):
    if spec["exit_code"] is None:
        return "Script completed\nOutput:\n(no exit code reported)"
    head = "Script failed\n" if spec["exit_code"] != 0 else "Script completed\n"
    body = "Exit code: {0}\nWall time: {1} seconds\nOutput:\n".format(spec["exit_code"], spec["wall"])
    if spec["mode"] == "timeout":
        body += "command timed out after 20054 milliseconds\n"
    else:
        body += "synthetic output line\n"
    return head + body


# ---------------------------------------------------------------------------
# truth.json / manifest.json
# ---------------------------------------------------------------------------


def build_truth(rules):
    thresholds = rules.thresholds
    precision = rules.params["rate_precision"]
    window = int(rules.params["retry"]["window_seconds"])
    # 用与渲染完全相同的 seed 重建调用序列 → 期望重试次数由真实序列复算（非植入断言）
    pairs_by_server = dict(
        (server, pairs) for server, _session, pairs in _build_claude_events(SplitMix64(DEFAULT_SEED))
    )
    servers = []
    for spec in SERVER_SPECS:
        rate = expected_failure_rate(spec["ok"], spec["error"], precision)
        modes = {}
        for mode in spec["modes"]:
            modes[mode] = {
                "calls": spec["modes"][mode],
                "rule_id": _rule_id_for_mode(rules, mode),
                "rule_effective": _rule_effective(rules, mode),
            }
        servers.append(
            {
                "server": spec["server"],
                "shape": spec["shape"],
                "calls_total": spec["calls"],
                "calls_ok": spec["ok"],
                "calls_error": spec["error"],
                "calls_unknown": spec["unknown"],
                "expected_failure_rate": rate,
                "expected_suggestion": expected_suggestion(
                    spec["calls"], spec["ok"], spec["error"], thresholds, precision
                ),
                "expected_retry_count": _expected_retry_count(
                    spec["server"], pairs_by_server[spec["server"]], window
                ),
                "failure_modes": modes,
            }
        )

    codex_ok = 0
    codex_error = 0
    codex_unknown = 0
    codex_modes = {}
    for spec in CODEX_CALLS:
        if spec["exit_code"] is None:
            codex_unknown += 1
            continue
        if spec["exit_code"] == 0:
            codex_ok += 1
            continue
        codex_error += 1
        mode = spec["mode"]
        codex_modes[mode] = codex_modes.get(mode, 0) + 1

    return {
        "seed": DEFAULT_SEED,
        "generator": "tools/gen_synthetic_logs.py",
        "note": "真值库只存输入与期望；观测由基准运行时实算（K12）。",
        "rules_snapshot": {
            "remove_candidate": thresholds["remove_candidate"],
            "investigate": thresholds["investigate"],
            "min_samples": thresholds["min_samples"],
            "rate_precision": precision,
        },
        "claude": {"servers": servers},
        "codex": {
            "server": "<codex>",
            "session_id": "sess-codex-alpha",
            "source_version": CODEX_CLI_VERSION,
            "calls_total": len(CODEX_CALLS),
            "calls_ok": codex_ok,
            "calls_error": codex_error,
            "calls_unknown": codex_unknown,
            "expected_failure_rate": expected_failure_rate(codex_ok, codex_error, precision),
            "expected_suggestion": expected_suggestion(
                len(CODEX_CALLS), codex_ok, codex_error, thresholds, precision
            ),
            "failure_modes": dict(
                (mode, {"calls": codex_modes[mode], "rule_id": _rule_id_for_mode(rules, mode),
                        "rule_effective": _rule_effective(rules, mode)})
                for mode in sorted(codex_modes)
            ),
            "token_attribution": "session_level_only",
        },
        "boundary_cases": [
            {
                "server": "fake-threshold-exact",
                "kind": "threshold_exact",
                "note": "failure_rate 恰等于 remove_candidate.failure_rate_gte，期望命中（验 ≥ 语义）",
            },
            {
                "server": "fake-near-miss",
                "kind": "near_miss",
                "note": "failure_rate 低于 remove_candidate.failure_rate_gte，期望不命中 remove_candidate",
            },
        ],
        "reverse_cases": [
            {
                "server": "fake-low-fail",
                "kind": "reverse",
                "note": "低失败率 server，期望不出 remove_candidate（反向样例）",
            }
        ],
        "three_state": {
            "ok": "tool_result.is_error=false",
            "error": "tool_result.is_error=true",
            "unknown": "tool_result 无 is_error 键（含部分带错误文本的缺失样本）",
        },
    }


def _rule_id_for_mode(rules, mode):
    for rule in rules.patterns.get("rules", []):
        if rule.get("category") == mode:
            return rule.get("id")
    return None


def _rule_effective(rules, mode):
    for rule in rules.effective_patterns():
        if rule.get("category") == mode:
            return True
    return False


def build_manifest(rules, truth):
    servers = truth["claude"]["servers"]
    claude_total = sum(s["calls_total"] for s in servers)
    codex_total = truth["codex"]["calls_total"]

    mode_counts = {}
    for server in servers:
        for mode in server["failure_modes"]:
            mode_counts[mode] = mode_counts.get(mode, 0) + server["failure_modes"][mode]["calls"]
    for mode in truth["codex"]["failure_modes"]:
        mode_counts[mode] = mode_counts.get(mode, 0) + truth["codex"]["failure_modes"][mode]["calls"]

    state_counts = {"ok": 0, "error": 0, "unknown": 0}
    for server in servers:
        state_counts["ok"] += server["calls_ok"]
        state_counts["error"] += server["calls_error"]
        state_counts["unknown"] += server["calls_unknown"]
    state_counts["ok"] += truth["codex"]["calls_ok"]
    state_counts["error"] += truth["codex"]["calls_error"]
    state_counts["unknown"] += truth["codex"]["calls_unknown"]

    required_modes = ("timeout", "permission_denied", "invalid_args", "content_refusal")

    coverage = [
        {
            "dimension": "server_failure_rate",
            "required_forms": 4,
            "sampled_forms": len([s for s in servers if s["shape"] in ("high", "mid", "low", "retry")]),
            "items": [
                {
                    "form": s["shape"],
                    "server": s["server"],
                    "sampled_calls": s["calls_total"],
                    "expected_failure_rate": s["expected_failure_rate"],
                }
                for s in servers
                if s["shape"] in ("high", "mid", "low", "retry")
            ],
        },
        {
            "dimension": "failure_mode",
            "required_forms": len(required_modes),
            "sampled_forms": len([m for m in required_modes if mode_counts.get(m)]),
            "items": [
                {"form": mode, "sampled_calls": mode_counts.get(mode, 0)} for mode in required_modes
            ],
        },
        {
            "dimension": "three_state",
            "required_forms": 3,
            "sampled_forms": len([k for k in ("ok", "error", "unknown") if state_counts[k] > 0]),
            "items": [
                {"form": state, "sampled_calls": state_counts[state]} for state in ("ok", "error", "unknown")
            ],
        },
        {
            "dimension": "threshold_boundary",
            "required_forms": 2,
            "sampled_forms": len(truth["boundary_cases"]),
            "items": [
                {"form": case["kind"], "server": case["server"]} for case in truth["boundary_cases"]
            ],
        },
        {
            "dimension": "reverse_case",
            "required_forms": 1,
            "sampled_forms": len(truth["reverse_cases"]),
            "items": [{"form": case["kind"], "server": case["server"]} for case in truth["reverse_cases"]],
        },
    ]

    return {
        "seed": DEFAULT_SEED,
        "generator": "tools/gen_synthetic_logs.py",
        "declaration": "抽样覆盖，非穷举：以下为最低覆盖项的登记，不代表真实世界的分布。",
        "totals": {
            "claude_calls": claude_total,
            "codex_calls": codex_total,
            "calls_total": claude_total + codex_total,
            "servers_sampled": len(servers),
            "logs": [CLAUDE_LOG, CODEX_LOG],
        },
        "coverage": coverage,
        "servers": [
            {
                "server": s["server"],
                "shape": s["shape"],
                "calls_total": s["calls_total"],
                "calls_ok": s["calls_ok"],
                "calls_error": s["calls_error"],
                "calls_unknown": s["calls_unknown"],
                "expected_failure_rate": s["expected_failure_rate"],
                "expected_suggestion": s["expected_suggestion"],
            }
            for s in servers
        ],
        "rules_pack": {
            "path": "data/rules",
            "total_rules": len(rules.patterns.get("rules", [])),
            "effective_rules": len(rules.effective_patterns()),
            "rules": [
                {
                    "id": rule.get("id"),
                    "category": rule.get("category"),
                    "status": rule.get("status"),
                    "verified_samples": len(rule.get("verified_samples") or []),
                    "effective": rule.get("id") in [r.get("id") for r in rules.effective_patterns()],
                }
                for rule in rules.patterns.get("rules", [])
            ],
        },
    }


# ---------------------------------------------------------------------------
# 产物构建与写盘
# ---------------------------------------------------------------------------


def _validate_specs():
    """生成前自校验：calls = ok + error + unknown；modes 合计 = error。"""
    problems = []
    for spec in SERVER_SPECS:
        if spec["ok"] + spec["error"] + spec["unknown"] != spec["calls"]:
            problems.append("{0}: calls != ok+error+unknown".format(spec["server"]))
        if sum(spec["modes"][m] for m in spec["modes"]) != spec["error"]:
            problems.append("{0}: modes 合计 != error".format(spec["server"]))
        if not spec["server"].startswith("fake-"):
            problems.append("{0}: server 名不在 fake-* 白名单".format(spec["server"]))
    if problems:
        raise SystemExit("[gen] 规格自校验失败：{0}".format("; ".join(problems)))


def build_outputs(rules_dir=None):
    """构建全部产物：返回有序 (相对路径, 文本) 列表。"""
    _validate_specs()
    rules = config.load_rules(rules_dir or DEFAULT_RULES_DIR)
    _validate_retry_separation(rules)
    rng = SplitMix64(DEFAULT_SEED)
    claude_lines = render_claude_log(rng)
    codex_lines = render_codex_log(rng)
    truth = build_truth(rules)
    manifest = build_manifest(rules, truth)
    return [
        (CLAUDE_LOG, "".join(serialize.dumps_compact(row) + "\n" for row in claude_lines)),
        (CODEX_LOG, "".join(serialize.dumps_compact(row) + "\n" for row in codex_lines)),
        (TRUTH_FILE, serialize.dumps(truth)),
        (MANIFEST_FILE, serialize.dumps(manifest)),
    ]


def write_outputs(out_dir, outputs):
    for relative, text in outputs:
        serialize.write_atomic(os.path.join(out_dir, relative), text)
    return out_dir


def check_outputs(out_dir, outputs):
    """逐字节比对；返回不一致项列表（空 = 全部一致）。"""
    mismatches = []
    for relative, text in outputs:
        path = os.path.join(out_dir, relative)
        if not os.path.isfile(path):
            mismatches.append("{0}: 缺失".format(relative))
            continue
        with open(path, "rb") as handle:
            on_disk = handle.read()
        if on_disk != text.encode("utf-8"):
            mismatches.append("{0}: 与重生成结果不一致".format(relative))
    return mismatches


def build_parser():
    parser = argparse.ArgumentParser(
        prog="gen_synthetic_logs",
        description="合成 MCP/工具调用日志与植入真值（确定性、无时钟、fake-* 白名单）",
    )
    parser.add_argument("--out", default=DEFAULT_OUT, help="产物输出目录（缺省 data/synthetic）")
    parser.add_argument("--rules-dir", default=None, help="规则包目录（期望建议按它推导）")
    parser.add_argument("--check", action="store_true", help="只校验冻结产物位级一致，不重跑写盘")
    return parser


def main(argv=None):
    _encoding.ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    out_dir = args.out if os.path.isabs(args.out) else os.path.join(_REPO_ROOT, args.out)

    outputs = build_outputs(args.rules_dir)
    if args.check:
        mismatches = check_outputs(out_dir, outputs)
        if mismatches:
            sys.stderr.write("[gen] 位级不一致：\n")
            for item in mismatches:
                sys.stderr.write("  - {0}\n".format(item))
            return exit_codes.EXIT_FINDINGS
        sys.stdout.write("[gen] --check 通过：{0} 个产物与重生成结果逐字节一致\n".format(len(outputs)))
        return exit_codes.EXIT_OK

    write_outputs(out_dir, outputs)
    sys.stdout.write("[gen] 已写出 {0} 个产物到 {1}\n".format(len(outputs), out_dir))
    for relative, text in outputs:
        sys.stdout.write("  - {0} ({1} bytes)\n".format(relative, len(text.encode("utf-8"))))
    return exit_codes.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
