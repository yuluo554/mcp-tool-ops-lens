"""解析层共享工具（模块 1）。

纯函数纪律：本模块不读规则包、不读时钟、不写盘。
口径参数（如错误文本截断上限）一律由调用方注入，不在代码里写字面量。
"""

import json
import os
import re

from .. import exit_codes


def read_json_file(path):
    """读一个 JSON 对象文件（只读，UTF-8）。

    注意：这里会整体载入文件内容（JSON 解析无法只读部分键），
    故调用方**必须**采用正向白名单提取，保证禁读键的值不进入任何数据结构
    （见 `claude_config` 的模块 docstring 与 `tests/test_privacy.py`）。
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise exit_codes.DataUnavailableError("配置文件不是合法 JSON：{0}（{1}）".format(path, exc))
    if not isinstance(data, dict):
        raise exit_codes.DataUnavailableError("配置文件顶层必须是对象：{0}".format(path))
    return data


def iter_jsonl(path):
    """逐行产出 `(源行号, 对象)`；源行号即 IR 的 `seq` 来源（K11）。

    空行跳过（不占行号语义，因为行号取自 enumerate，跳过的空行仍占号——
    这正是"seq = 源行号"而不是"事件数组下标"的意义所在）。

    非法 JSON 一律报错：静默跳过会让计数偏低，属"把未声明态洗成不存在"。
    """
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                raise exit_codes.DataUnavailableError(
                    "日志行不是合法 JSON：{0}:{1}（{2}）".format(path, line_no, exc)
                )
            if not isinstance(obj, dict):
                raise exit_codes.DataUnavailableError(
                    "日志行顶层必须是对象：{0}:{1}".format(path, line_no)
                )
            yield line_no, obj


def peek_first_object(path):
    """取首条非空行对象；空文件返回 None。"""
    for _line_no, obj in iter_jsonl(path):
        return obj
    return None


def text_of_content(content):
    """把 `tool_result.content` / Codex `output` 归一为文本。

    支持三种实测形态：裸字符串、块列表（`{"type": "text", "text": ...}`）、
    单块对象。**只取文本，绝不复制 `input` 等可能含源码/参数的载荷。**
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    return ""


_WHITESPACE_RUN = re.compile(r"\s+")


def truncate_error_text(text, max_chars=None):
    """错误文本进 IR 前的归一与截断（plan/04 §二：`prompt` / 代码正文永不落产物）。

    **M3 修正（实测发现的接口缺陷）**：旧实现取"首行"，会**丢掉模块 3 归因所需的失败签名**——
    实测两侧日志的失败信号都不在首行：Claude 侧为
    `Exit code 143` + 换行 + `Command timed out after ...`；Codex 侧为
    `Script failed` + 换行 + `Exit code: 124` + 换行 + `Wall time: ...`。
    只留首行时，规则表里 `Command timed out after` / `Exit code: 124` 这两条**永远无法命中**，
    归因结果必然与真值不符（探针实测：timeout 全部落 `other`）。

    现改为**空白归一**：把连续空白（含换行）折叠为单个空格，得到单行文本后再按
    `max_chars` 截断。这样既保住失败签名，又保持"单行 + 上限"的隐私形态
    （多行代码正文的版式不会进产物；上限仍由 `params.json` 注入）。
    该归一形态与规则表 `verified_samples` 的台账记法一致（如
    `Exit code 143 / Command timed out after 10m 0s`）。

    `max_chars` 由调用方从 `data/rules/params.json` 注入（`error_text.max_chars`），
    传 None 表示不截断。
    """
    normalized = _WHITESPACE_RUN.sub(" ", (text or "")).strip()
    if max_chars is not None and max_chars > 0 and len(normalized) > max_chars:
        return normalized[:max_chars]
    return normalized


def session_id_from_path(path):
    """会话 id 兜底：日志文件名（去扩展名）。确定性，不读时钟。"""
    return os.path.splitext(os.path.basename(path))[0]
