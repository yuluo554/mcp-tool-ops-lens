"""数据源发现与格式判别（模块 1 前置检查，plan/03 §1.3）。

`--home` 下的候选日志**递归**扫描，按首条非空行的**形态**判别归属解析器：

  · Codex：首行 `type == "session_meta"`（或有 `payload` 键）
  · Claude：首行 `type` ∈ {`system`, `assistant`, `user`}（或有 `message` / `version` 键）

判别用**形态**而非路径：本机真实布局（`~/.claude/projects/*/*.jsonl`、
`~/.codex/sessions/**/rollout-*.jsonl`）与合成演示目录（`data/synthetic/logs/*.jsonl`）
都能走同一条通路，测试与演示无需造假的目录树。

纪律：
  · 目录不存在 / 无任何候选日志 → `DataUnavailableError`（exit 4），
    **不是 0，也不是静默空报告**（空报告看起来像"没问题"，是本题要防的形态）。
  · 排序键用规范化后的相对路径，保证跨平台（`\\` 与 `/`）确定。
  · 纯函数：不读规则包、不读时钟、不写盘。
"""

import os

from .. import exit_codes
from . import common

KIND_CLAUDE_JSONL = "claude_jsonl"
KIND_CODEX_ROLLOUT = "codex_rollout"

_LOG_SUFFIX = ".jsonl"

_CLAUDE_ROW_TYPES = ("system", "assistant", "user", "summary")


def classify_first_row(obj):
    """按首行形态判别解析器；无法判别 → None。"""
    if not isinstance(obj, dict):
        return None
    if obj.get("type") == "session_meta" or "payload" in obj:
        return KIND_CODEX_ROLLOUT
    if obj.get("type") in _CLAUDE_ROW_TYPES or "message" in obj or "version" in obj:
        return KIND_CLAUDE_JSONL
    return None


def _normalized_relative(path, root):
    return os.path.relpath(path, root).replace(os.sep, "/")


def discover_logs(home):
    """递归发现 `home` 下的候选日志。

    返回 `(sources, skipped)`：
      · `sources` = `[{"path", "relative", "kind"}]`，按相对路径排序（确定性）
      · `skipped` = 无法判别形态的 jsonl 清单（显式登记，不静默丢弃）
    """
    if not os.path.isdir(home):
        raise exit_codes.DataUnavailableError("数据源目录不存在：{0}".format(home))

    candidates = []
    for dirpath, dirnames, filenames in os.walk(home):
        dirnames[:] = sorted(
            name for name in dirnames if name not in ("__pycache__", ".git", ".venv")
        )
        for name in sorted(filenames):
            if name.endswith(_LOG_SUFFIX):
                candidates.append(os.path.join(dirpath, name))

    sources = []
    skipped = []
    for path in candidates:
        first = common.peek_first_object(path)
        if first is None:
            skipped.append({"path": path, "reason": "empty_file"})
            continue
        kind = classify_first_row(first)
        if kind is None:
            skipped.append({"path": path, "reason": "unrecognized_shape"})
            continue
        sources.append({"path": path, "relative": _normalized_relative(path, home), "kind": kind})

    sources.sort(key=lambda item: item["relative"])
    skipped.sort(key=lambda item: item["path"])

    if not sources:
        raise exit_codes.DataUnavailableError(
            "数据源目录下没有可解析的会话日志：{0}"
            "（扫描面 {1} 个 jsonl，其中 {2} 个无法判别形态）——"
            "按纪律不产出空报告，请用 --home 指定正确的数据源根目录。".format(
                home, len(candidates), len(skipped)
            )
        )
    return sources, skipped
