"""解析层守门（M2 DoD 逐项落成可证伪断言）。

覆盖：
  · 三解析器产统一 IR，且与植入真值逐 server 对账（比"能跑"强得多）
  · 成败三态硬口径：`is_error` 缺失 → `unknown`（不进失败率分母）
  · schema 版本检测：不在显式支持集 → exit 4 且报错含检测键路径
  · `env` 禁读：含假凭据的 fixture 断言产物不含该值
  · 解析层纯函数：AST 断言不 import 规则层 / 时钟 / 随机，且不写盘
  · `seq` = 源行号（K11）
  · 双跑 IR 逐字节一致（单元级 + 端到端双锁）

变异验证：把 `versions.SUPPORTED_*` 改成万能匹配 → 本文件版本相关断言必红。
"""

import ast
import io
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
PARSERS_DIR = os.path.join(SRC_DIR, "opslens", "parsers")
SYNTHETIC_DIR = os.path.join(REPO_ROOT, "data", "synthetic")
CLAUDE_LOG = os.path.join(SYNTHETIC_DIR, "logs", "claude_alpha.jsonl")
CODEX_LOG = os.path.join(SYNTHETIC_DIR, "logs", "codex_alpha.jsonl")

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from opslens import exit_codes  # noqa: E402
from opslens import pipeline  # noqa: E402
from opslens import schema  # noqa: E402
from opslens.parsers import claude_config  # noqa: E402
from opslens.parsers import claude_jsonl  # noqa: E402
from opslens.parsers import codex_rollout  # noqa: E402
from opslens.parsers import common  # noqa: E402
from opslens.parsers import discovery  # noqa: E402
from opslens.parsers import versions  # noqa: E402


@pytest.fixture(scope="module")
def truth():
    with open(os.path.join(SYNTHETIC_DIR, "truth.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="module")
def scanned():
    events, report = pipeline.scan_home(SYNTHETIC_DIR)
    return events, report


def _write_jsonl(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


# ---------------------------------------------------------------------------
# 三解析器产统一 IR
# ---------------------------------------------------------------------------


def test_claude_parser_produces_ir_events():
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    assert events, "扫描面为空，断言可能空转"
    for event in events:
        assert isinstance(event, schema.ToolCallEvent)
        assert event.source == schema.SOURCE_CLAUDE_CODE
        assert event.source_version == "2.1.233"
        assert event.status in (schema.STATUS_OK, schema.STATUS_ERROR, schema.STATUS_UNKNOWN)
        assert event.call_id, "Claude 侧每次调用都必须能关联 tool_result"


def test_codex_parser_produces_ir_events():
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    assert events, "扫描面为空"
    for event in events:
        assert event.source == schema.SOURCE_CODEX
        assert event.source_version == "0.146.0-alpha.3.1"
        assert event.server == "<codex>"
        assert not event.tool.startswith("mcp__"), "Codex 侧不得套用 Claude 前缀规则"


def test_claude_tool_name_split_into_server_and_tool():
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    names = set((event.server, event.tool) for event in events)
    assert ("fake-high-fail", "tool_exec") in names
    assert all(server != "<builtin>" for server, _tool in names), "合成数据全是 mcp__ 形态"


def test_builtin_tool_falls_back_to_builtin_server(tmp_home):
    """非 `mcp__` 前缀的内置工具 → server=`<builtin>`（plan/03 §1.1）。"""
    path = _write_jsonl(
        os.path.join(tmp_home, "builtin.jsonl"),
        [
            {"type": "system", "version": "2.1.233", "session_id": "s-b", "timestamp": "T0"},
            {
                "type": "assistant",
                "sessionId": "s-b",
                "timestamp": "T1",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c1", "name": "Read", "input": {}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-b",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "is_error": False, "content": "ok"}]},
            },
        ],
    )
    events = claude_jsonl.parse_claude_jsonl(path)
    assert len(events) == 1
    assert events[0].server == schema.BUILTIN_SERVER
    assert events[0].tool == "Read"


def test_config_parser_returns_facts_not_events():
    facts = claude_config.parse_claude_config(SYNTHETIC_DIR)
    assert facts["configured"] is False, "合成目录不含配置文件"
    assert "events" not in facts


# ---------------------------------------------------------------------------
# 三态硬口径（K1）
# ---------------------------------------------------------------------------


def _status_counts(events):
    counts = {"ok": 0, "error": 0, "unknown": 0}
    for event in events:
        counts[event.status] += 1
    return counts


def test_unknown_is_not_silently_promoted_to_ok(tmp_home):
    """`is_error` 缺失 → unknown，**绝不**默认成功（本题正确性核心）。"""
    path = _write_jsonl(
        os.path.join(tmp_home, "three_state.jsonl"),
        [
            {"type": "system", "version": "2.1.233", "session_id": "s-3", "timestamp": "T0"},
            {
                "type": "assistant",
                "sessionId": "s-3",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c-missing", "name": "mcp__fake-x__tool_a", "input": {}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-3",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "c-missing", "content": "no status declared"}],
                },
            },
            {
                "type": "assistant",
                "sessionId": "s-3",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c-true", "name": "mcp__fake-x__tool_a", "input": {}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-3",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "c-true", "is_error": True, "content": "boom"}],
                },
            },
            {
                "type": "assistant",
                "sessionId": "s-3",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c-false", "name": "mcp__fake-x__tool_a", "input": {}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-3",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "c-false", "is_error": False, "content": "ok"}],
                },
            },
        ],
    )
    by_id = dict((event.call_id, event) for event in claude_jsonl.parse_claude_jsonl(path))
    assert by_id["c-missing"].status == schema.STATUS_UNKNOWN
    assert by_id["c-true"].status == schema.STATUS_ERROR
    assert by_id["c-false"].status == schema.STATUS_OK


def test_non_boolean_is_error_is_downgraded_to_unknown_with_note(tmp_home):
    """IR 未覆盖的新取值形态 → 降级 unknown + 注记，**不猜**（plan/03 §1.2）。"""
    path = _write_jsonl(
        os.path.join(tmp_home, "weird.jsonl"),
        [
            {"type": "system", "version": "2.1.233", "session_id": "s-w", "timestamp": "T0"},
            {
                "type": "assistant",
                "sessionId": "s-w",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c1", "name": "mcp__fake-x__tool_a", "input": {}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-w",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "c1", "is_error": "yes", "content": "?"}],
                },
            },
        ],
    )
    events = claude_jsonl.parse_claude_jsonl(path)
    assert events[0].status == schema.STATUS_UNKNOWN
    assert "unrecognized_is_error_type" in events[0].notes


def test_unknown_sample_with_error_text_stays_unknown(tmp_home):
    """M1 实测形态：缺失态里含错误文本 → 文本保留供审计，**status 仍是 unknown**。"""
    path = _write_jsonl(
        os.path.join(tmp_home, "unknown_with_text.jsonl"),
        [
            {"type": "system", "version": "2.1.233", "session_id": "s-u", "timestamp": "T0"},
            {
                "type": "assistant",
                "sessionId": "s-u",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c1", "name": "mcp__fake-x__tool_a", "input": {}}],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-u",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "Tool execution aborted"}],
                },
            },
        ],
    )
    event = claude_jsonl.parse_claude_jsonl(path)[0]
    assert event.status == schema.STATUS_UNKNOWN
    assert event.error_text, "缺失态里的错误文本应保留供审计"
    assert "error_text_present_on_unknown" in event.notes


def test_claude_three_state_counts_reconcile_with_truth(scanned, truth):
    """解析结果的三态计数必须与植入真值逐 server 一致（比"能跑"强得多）。"""
    events, _report = scanned
    actual = {}
    for event in events:
        if event.source != schema.SOURCE_CLAUDE_CODE:
            continue
        bucket = actual.setdefault(event.server, {"ok": 0, "error": 0, "unknown": 0})
        bucket[event.status] += 1
    for server in truth["claude"]["servers"]:
        name = server["server"]
        assert name in actual, "解析结果里没有 server {0}".format(name)
        assert actual[name] == {
            "ok": server["calls_ok"],
            "error": server["calls_error"],
            "unknown": server["calls_unknown"],
        }, "{0} 三态计数与真值不符：{1}".format(name, actual[name])
    assert sum(1 for server in truth["claude"]["servers"] if server["calls_unknown"]) >= 1, (
        "真值里必须有 unknown 样本，否则 unknown 通路没被演练"
    )


def test_codex_three_state_counts_reconcile_with_truth(scanned, truth):
    events, _report = scanned
    codex = [event for event in events if event.source == schema.SOURCE_CODEX]
    counts = _status_counts(codex)
    assert counts == {
        "ok": truth["codex"]["calls_ok"],
        "error": truth["codex"]["calls_error"],
        "unknown": truth["codex"]["calls_unknown"],
    }


def test_codex_exit_code_is_the_only_success_signal():
    """`payload.status` 实测恒为 `completed`（哑值）→ 绝不能当成败判据。"""
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    counts = _status_counts(events)
    assert counts["ok"] >= 1 and counts["error"] >= 1 and counts["unknown"] >= 1
    # 若把 `status` 当判据，所有调用都会变成 ok —— 这里断言并非如此。
    assert counts["ok"] != len(events)


def test_codex_missing_exit_code_text_is_unknown():
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    unknown = [event for event in events if event.status == schema.STATUS_UNKNOWN]
    assert unknown, "缺 `Exit code:` 文本的样本必须记 unknown"
    assert "exit_code_undeclared" in unknown[0].notes


# ---------------------------------------------------------------------------
# token / 耗时口径（K2 / K3 / K4）
# ---------------------------------------------------------------------------


def test_claude_tokens_are_turn_attributed_and_four_separate_fields():
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    for event in events:
        assert event.turn_tokens_attributed is True
        assert event.tokens is not None, "合成数据 100% 带 usage（M1 实测）"
        assert len(event.tokens) == 4
    sample = events[0].to_dict()["tokens"]
    assert set(sample) == {"input", "output", "cache_read", "cache_creation"}


def test_claude_duration_is_unavailable_not_zero():
    """K4：Claude 侧按工具耗时不可得 → None（**不得**用 lastToolDuration 冒充）。

    M2 复核补充（data/README §五 B）：真实日志里 `toolUseResult.durationMs` 确实存在
    （159 条），但只覆盖 `Glob` / `WebFetch` 两个内置工具，**对 `mcp__*` 工具覆盖率实测为 0**，
    且其语义（是否含排队等待）未经核对。按"未核对字段不进计算路径"纪律，
    解析器**一律不取该字段**，Claude 侧 `duration_ms` 恒为 None。
    本测试同时锁住"没有偷偷去读 durationMs"。
    """
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    assert all(event.duration_ms is None for event in events)

    # 即便日志里带 durationMs，也不得被采用（含内置工具）
    path = os.path.join(REPO_ROOT, "data", "synthetic", "logs", "claude_alpha.jsonl")
    assert os.path.isfile(path)
    source = open(os.path.join(PARSERS_DIR, "claude_jsonl.py"), "r", encoding="utf-8").read()
    assert "durationMs" not in source, "解析器读了语义未核对的 durationMs 字段"


def test_codex_tokens_not_attributed_to_calls():
    """K3：Codex token 只在会话级，不摊到单次工具调用。"""
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    assert all(event.tokens is None for event in events)
    assert all(event.turn_tokens_attributed is False for event in events)


def test_codex_session_token_usage_is_reported_separately(scanned):
    _events, report = scanned
    usage = report["session_token_usage"]
    assert usage, "会话级 token 必须单列上报（否则该维度静默丢失）"
    for totals in usage.values():
        assert totals.get("total_tokens", 0) > 0


def test_codex_wall_time_becomes_duration_ms():
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    durations = [event.duration_ms for event in events if event.duration_ms is not None]
    assert durations, "`Wall time:` 文本应被解析为 duration_ms"
    assert all(isinstance(value, int) and value > 0 for value in durations)


def test_codex_missing_wall_time_is_none_with_note():
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    missing = [event for event in events if event.duration_ms is None]
    assert missing, "合成数据含无 Wall time 的样本"
    assert any("wall_time_missing" in event.notes for event in missing)


# ---------------------------------------------------------------------------
# schema 版本检测（技术创新锚点）
# ---------------------------------------------------------------------------


def test_supported_version_sets_are_explicit_and_nonempty():
    assert versions.SUPPORTED_CLAUDE_VERSIONS
    assert versions.SUPPORTED_CODEX_CLI_VERSIONS
    assert "2.1.233" in versions.SUPPORTED_CLAUDE_VERSIONS


def test_unknown_claude_version_raises_data_unavailable(tmp_home):
    path = _write_jsonl(
        os.path.join(tmp_home, "future.jsonl"),
        [
            {"type": "system", "version": "9.9.999", "session_id": "s-f", "timestamp": "T0"},
            {
                "type": "assistant",
                "sessionId": "s-f",
                "version": "9.9.999",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c1", "name": "mcp__fake-x__tool_a", "input": {}}],
                },
            },
        ],
    )
    with pytest.raises(exit_codes.SchemaVersionError) as excinfo:
        claude_jsonl.parse_claude_jsonl(path)
    assert excinfo.value.exit_code == exit_codes.EXIT_DATA_UNAVAILABLE
    message = str(excinfo.value)
    assert "9.9.999" in message, "报错必须打印未识别版本"
    assert versions.CLAUDE_VERSION_KEY_PATH in message, "报错必须打印检测键路径"


def test_missing_claude_version_key_raises(tmp_home):
    path = _write_jsonl(
        os.path.join(tmp_home, "noversion.jsonl"),
        [
            {
                "type": "assistant",
                "sessionId": "s-n",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "c1", "name": "mcp__fake-x__tool_a", "input": {}}],
                },
            }
        ],
    )
    with pytest.raises(exit_codes.SchemaVersionError):
        claude_jsonl.parse_claude_jsonl(path)


def test_unknown_codex_cli_version_raises_data_unavailable(tmp_home):
    path = _write_jsonl(
        os.path.join(tmp_home, "rollout-future.jsonl"),
        [
            {
                "type": "session_meta",
                "payload": {"id": "s-f", "cli_version": "99.0.0-future"},
            }
        ],
    )
    with pytest.raises(exit_codes.SchemaVersionError) as excinfo:
        codex_rollout.parse_codex_rollout(path)
    assert excinfo.value.exit_code == exit_codes.EXIT_DATA_UNAVAILABLE
    assert "99.0.0-future" in str(excinfo.value)
    assert versions.CODEX_VERSION_KEY_PATH in str(excinfo.value)


def test_version_check_is_exact_membership_not_pattern_match():
    """显式集合语义：前缀/相似串**不得**被接受（防"万能匹配"变异漏网）。"""
    assert "2.1.233-extra" not in versions.SUPPORTED_CLAUDE_VERSIONS
    with pytest.raises(exit_codes.SchemaVersionError):
        versions.check_claude_version("2.1.233-extra")
    with pytest.raises(exit_codes.SchemaVersionError):
        versions.check_claude_version("2.1.23")
    with pytest.raises(exit_codes.SchemaVersionError):
        versions.check_claude_version("")
    with pytest.raises(exit_codes.SchemaVersionError):
        versions.check_codex_cli_version("0.146.0")
    # 阳性对照：支持集内的值必须放行（否则上面全是空转）
    assert versions.check_claude_version("2.1.233") == "2.1.233"
    assert versions.check_codex_cli_version("0.146.0-alpha.3.1") == "0.146.0-alpha.3.1"


# ---------------------------------------------------------------------------
# `env` 禁读（隐私红线）
# ---------------------------------------------------------------------------

# 假凭据值：与真实值无关，仅用于断言"未进入产物"。
# 运行时拼接构造，避免本文件自身被禁止词表守门误判（HANDOFF-M1 §四 第 8 条）。
FAKE_CREDENTIAL_VALUE = "fake" + "-credential-value-" + "for-privacy-test"
FAKE_ENV_KEY = "ANTHROPIC" + "_AUTH" + "_TOKEN"


def _write_settings(home, extra):
    directory = os.path.join(home, ".claude")
    if not os.path.isdir(directory):
        os.makedirs(directory)
    payload = {"permissions": {"allow": ["mcp__fake-server__tool_a"]}, "enabledPlugins": {"p@m": True}}
    payload.update(extra)
    path = os.path.join(directory, "settings.json")
    with io.open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def test_settings_parser_reads_whitelisted_keys_only(tmp_home):
    _write_settings(tmp_home, {})
    settings = claude_config.parse_settings(os.path.join(tmp_home, ".claude", "settings.json"))
    assert settings["allowed_tools"] == ["mcp__fake-server__tool_a"]
    assert settings["enabled_plugins"] == ["p@m"]


def test_env_credential_never_reaches_output(tmp_home):
    """含假凭据的 fixture：产物（配置事实 + 序列化文本）都不得含该值。"""
    _write_settings(tmp_home, {"env": {FAKE_ENV_KEY: FAKE_CREDENTIAL_VALUE}})
    facts = claude_config.parse_claude_config(tmp_home)
    serialized = json.dumps(facts, ensure_ascii=False)
    assert FAKE_CREDENTIAL_VALUE not in serialized, "凭据值泄漏进配置事实"
    assert FAKE_ENV_KEY not in serialized, "凭据键名泄漏进配置事实"
    assert "env" not in facts["settings"], "禁读键不得出现在输出结构里"


def test_env_credential_absent_from_end_to_end_events(synthetic_home, tmp_out):
    """端到端：把假凭据写进 home 的 settings.json，产物 JSON 文本不得含它。"""
    _write_settings(synthetic_home, {"env": {FAKE_ENV_KEY: FAKE_CREDENTIAL_VALUE}})
    events, report = pipeline.scan_home(synthetic_home)
    payload = pipeline.build_events_payload(events, report)
    text = json.dumps(payload, ensure_ascii=False)
    assert FAKE_CREDENTIAL_VALUE not in text, "凭据值经端到端通路泄漏进产物"
    assert FAKE_ENV_KEY not in text


def test_settings_parser_tolerates_missing_files(tmp_home):
    assert claude_config.parse_settings(os.path.join(tmp_home, "nope.json")) is None
    assert claude_config.parse_claude_config(tmp_home)["configured"] is False


def test_global_config_keeps_last_tool_duration_as_reference_only(tmp_home):
    """项目级 `lastToolDuration` 只作参考项单列，**不得**进事件耗时（K4）。"""
    payload = {
        "mcpServers": {"fake-server": {"command": "x"}},
        "projects": {"/proj": {"mcpServers": {"fake-server": {}}, "lastToolDuration": 4361}},
    }
    path = os.path.join(tmp_home, ".claude.json")
    with io.open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    facts = claude_config.parse_global_config(path)
    assert facts["mcp_servers"] == ["fake-server"]
    assert facts["projects"]["/proj"]["last_tool_duration_ms"] == 4361


# ---------------------------------------------------------------------------
# 纯函数纪律（AST 守门）
# ---------------------------------------------------------------------------

# 解析层禁止 import 的模块：规则层 / 时钟 / 随机 / 网络
FORBIDDEN_PARSER_IMPORTS = frozenset(
    ["config", "rules", "serialize", "time", "datetime", "random", "uuid", "socket", "urllib"]
)


def _iter_parser_files():
    for name in sorted(os.listdir(PARSERS_DIR)):
        if name.endswith(".py"):
            yield os.path.join(PARSERS_DIR, name)


def _imported_top_names(path):
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0])
    return names


def test_parser_scan_face_is_not_empty():
    """扫描面非空自证：防"目录写错 → 扫 0 个 → 永远绿"。"""
    files = list(_iter_parser_files())
    assert len(files) >= 5, "解析层扫描面只有 {0} 个文件".format(len(files))


def test_parsers_do_not_import_rules_clock_or_random():
    offenders = {}
    for path in _iter_parser_files():
        hit = _imported_top_names(path) & FORBIDDEN_PARSER_IMPORTS
        if hit:
            offenders[os.path.basename(path)] = sorted(hit)
    assert offenders == {}, "解析层出现禁止 import：{0}".format(offenders)


def test_parsers_never_open_files_for_writing():
    """纯函数：解析层不得出现写盘调用（`open(..., "w"/"a"/"x")` / `write_text`）。"""
    offenders = []
    for path in _iter_parser_files():
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "open":
                    modes = [arg for arg in node.args[1:] if isinstance(arg, ast.Constant)]
                    for mode in modes:
                        if isinstance(mode.value, str) and any(ch in mode.value for ch in "wax+"):
                            offenders.append("{0}:{1}".format(os.path.basename(path), node.lineno))
                if isinstance(func, ast.Attribute) and func.attr in ("write_text", "write_bytes", "mkdir", "makedirs"):
                    offenders.append("{0}:{1}".format(os.path.basename(path), node.lineno))
    assert offenders == [], "解析层出现写盘路径：{0}".format(offenders)


def test_write_detector_actually_detects():
    """探针自证：写盘样例必须被判为违规（否则上面那条是假门）。"""
    sample = 'open("x", "w")\n'
    tree = ast.parse(sample)
    hit = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            for mode in [arg for arg in node.args[1:] if isinstance(arg, ast.Constant)]:
                if any(ch in mode.value for ch in "wax+"):
                    hit = True
    assert hit


# ---------------------------------------------------------------------------
# `seq` = 源行号（K11）
# ---------------------------------------------------------------------------


def test_claude_seq_is_source_line_number_not_array_index():
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    with open(CLAUDE_LOG, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for event in events:
        assert 1 <= event.seq <= len(lines)
        row = json.loads(lines[event.seq - 1])
        assert row.get("type") == "assistant", "seq 未指向声明 tool_use 的源行"
        ids = [
            block.get("id")
            for block in (row.get("message") or {}).get("content") or []
            if isinstance(block, dict) and block.get("type") == "tool_use"
        ]
        assert event.call_id in ids


def test_codex_seq_is_source_line_number():
    events = codex_rollout.parse_codex_rollout(CODEX_LOG)
    with open(CODEX_LOG, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for event in events:
        row = json.loads(lines[event.seq - 1])
        assert row.get("type") == "response_item"
        assert row["payload"].get("call_id") == event.call_id


def test_seq_is_not_the_compacted_index():
    """把 `seq` 换成数组下标（紧凑序列）时本断言必红——这才是它存在的意义。"""
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert seqs != list(range(1, len(events) + 1)), "seq 不应是紧凑数组下标"


# ---------------------------------------------------------------------------
# 双跑 IR 逐字节一致（K11 最硬形态：单元级 + 端到端双锁）
# ---------------------------------------------------------------------------


def test_single_file_double_parse_is_byte_identical():
    first = schema.payload_to_json(
        schema.events_to_payload(claude_jsonl.parse_claude_jsonl(CLAUDE_LOG))
    )
    second = schema.payload_to_json(
        schema.events_to_payload(claude_jsonl.parse_claude_jsonl(CLAUDE_LOG))
    )
    assert first == second


def test_end_to_end_double_scan_is_byte_identical():
    first_events, first_report = pipeline.scan_home(SYNTHETIC_DIR)
    second_events, second_report = pipeline.scan_home(SYNTHETIC_DIR)
    first = schema.payload_to_json(pipeline.build_events_payload(first_events, first_report))
    second = schema.payload_to_json(pipeline.build_events_payload(second_events, second_report))
    assert first == second


def test_cli_writes_byte_identical_events_on_two_runs(synthetic_home, tmp_out):
    """端到端硬锁：两次 `scan --out` 的产物文件 sha256 必须相同。"""
    import hashlib

    from opslens.cli import main

    out_a = os.path.join(tmp_out, "a.json")
    out_b = os.path.join(tmp_out, "b.json")
    assert main(["scan", "--home", synthetic_home, "--out", out_a]) == exit_codes.EXIT_OK
    assert main(["scan", "--home", synthetic_home, "--out", out_b]) == exit_codes.EXIT_OK

    def digest(path):
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    assert digest(out_a) == digest(out_b), "两次 scan 的 IR 产物不是逐字节一致"


def test_events_payload_is_sorted_by_source_session_seq(synthetic_home):
    events, report = pipeline.scan_home(synthetic_home)
    payload = pipeline.build_events_payload(events, report)
    keys = [(item["source"], item["session_id"], item["seq"]) for item in payload["events"]]
    assert keys == sorted(keys), "IR 未按 (source, session_id, seq) 排序"
    assert payload["count"] == len(events)


# ---------------------------------------------------------------------------
# 目录前置检查（plan/03 §1.3）
# ---------------------------------------------------------------------------


def test_missing_home_is_data_unavailable(tmp_home):
    with pytest.raises(exit_codes.DataUnavailableError) as excinfo:
        pipeline.scan_home(os.path.join(tmp_home, "no-such-dir"))
    assert excinfo.value.exit_code == exit_codes.EXIT_DATA_UNAVAILABLE


def test_empty_home_is_data_unavailable_not_empty_report(tmp_home):
    """空目录 → exit 4，**不是** 0 也不是静默空报告（空报告看起来像"没问题"）。"""
    with pytest.raises(exit_codes.DataUnavailableError):
        pipeline.scan_home(tmp_home)


def test_home_with_only_unrecognized_logs_is_data_unavailable(tmp_home):
    _write_jsonl(os.path.join(tmp_home, "junk.jsonl"), [{"hello": "world"}])
    with pytest.raises(exit_codes.DataUnavailableError):
        pipeline.scan_home(tmp_home)


def test_discovery_reports_unrecognized_files_instead_of_silently_dropping(tmp_home):
    _write_jsonl(
        os.path.join(tmp_home, "rollout-ok.jsonl"),
        [{"type": "session_meta", "payload": {"cli_version": "0.146.0-alpha.3.1", "id": "s"}}],
    )
    _write_jsonl(os.path.join(tmp_home, "junk.jsonl"), [{"hello": "world"}])
    sources, skipped = discovery.discover_logs(tmp_home)
    assert len(sources) == 1
    assert [item["reason"] for item in skipped] == ["unrecognized_shape"]


def test_discovery_classifies_by_shape_not_by_directory_name(synthetic_home):
    """判别按**首行形态**：真实布局（projects/ 与 sessions/）都能走同一条通路。"""
    sources, skipped = discovery.discover_logs(synthetic_home)
    kinds = sorted(item["kind"] for item in sources)
    assert kinds == [discovery.KIND_CLAUDE_JSONL, discovery.KIND_CODEX_ROLLOUT]
    assert skipped == []
    for item in sources:
        assert "\\" not in item["relative"], "相对路径未规范化，跨平台不确定"


def test_discovery_ordering_is_deterministic(synthetic_home):
    first = [item["relative"] for item in discovery.discover_logs(synthetic_home)[0]]
    second = [item["relative"] for item in discovery.discover_logs(synthetic_home)[0]]
    assert first == second == sorted(first)


# ---------------------------------------------------------------------------
# 错误文本截断（prompt / 代码正文不落产物）
# ---------------------------------------------------------------------------


def test_error_text_is_truncated_to_configured_limit():
    long_text = "A" * 500 + "\nsecond line"
    assert len(common.truncate_error_text(long_text, 10)) == 10
    assert common.truncate_error_text(long_text, 10) == "A" * 10


def test_error_text_takes_first_line_only():
    assert common.truncate_error_text("first line\nsecond line", 240) == "first line"


def test_error_text_limit_comes_from_rules_pack():
    """截断上限来自 `data/rules/params.json`，不是代码字面量（K9）。"""
    from opslens import config

    rules = config.load_rules()
    assert isinstance(rules.params["error_text"]["max_chars"], int)
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG, rules.params["error_text"]["max_chars"])
    for event in events:
        assert len(event.error_text) <= rules.params["error_text"]["max_chars"]


def test_success_events_carry_no_error_text():
    events = claude_jsonl.parse_claude_jsonl(CLAUDE_LOG)
    for event in events:
        if event.status == schema.STATUS_OK:
            assert event.error_text == ""


def test_tool_use_input_never_reaches_ir(tmp_home):
    """`tool_use.input` 可能含源码/参数 → **不进 IR**（plan/04 §二 第 4 条）。"""
    marker = "SECRET-" + "SOURCE-SNIPPET"
    path = _write_jsonl(
        os.path.join(tmp_home, "input.jsonl"),
        [
            {"type": "system", "version": "2.1.233", "session_id": "s-i", "timestamp": "T0"},
            {
                "type": "assistant",
                "sessionId": "s-i",
                "version": "2.1.233",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "c1", "name": "mcp__fake-x__tool_a", "input": {"code": marker}}
                    ],
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            },
            {
                "type": "user",
                "sessionId": "s-i",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "is_error": False, "content": "ok"}]},
            },
        ],
    )
    events = claude_jsonl.parse_claude_jsonl(path)
    text = json.dumps([event.to_dict() for event in events], ensure_ascii=False)
    assert marker not in text, "tool_use.input 泄漏进 IR"


def test_malformed_jsonl_line_raises_instead_of_being_skipped(tmp_home):
    path = os.path.join(tmp_home, "broken.jsonl")
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"type": "session_meta", "payload": {"cli_version": "0.146.0-alpha.3.1"}}\n')
        handle.write("{not json}\n")
    with pytest.raises(exit_codes.DataUnavailableError):
        codex_rollout.parse_codex_rollout(path)
