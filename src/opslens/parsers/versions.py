"""schema 版本检测（题目"技术创新"锚点，plan/03 §1.2）。

**显式常量集合，不是正则放宽匹配**：解析时检测键的取值不在集合内 → 报错（exit 4）
并打印"未识别版本 + 期望集合 + 检测键路径"。**绝不静默按最宽松规则解析**——
静默错解正是本题点名要防的。

检测键（M1 本机实测确定）：
  · Claude Code：日志行顶层 `version`（实测 2.1.216/220/223/226/233/238/263）
  · Codex：`session_meta.payload.cli_version`（实测 0.146.0-alpha.3.1）

本模块是**纯函数**：只做集合判定，不读规则包、不读时钟、不写盘。
"""

from .. import exit_codes

# 检测键路径（报错信息里原样打印，便于用户定位日志里的字段）
CLAUDE_VERSION_KEY_PATH = "version"
CODEX_VERSION_KEY_PATH = "session_meta.payload.cli_version"

# 显式支持集：新增支持版本必须**手写进这里**（可审计、可 diff），
# 不允许"任意字符串都算支持"的宽松匹配。
SUPPORTED_CLAUDE_VERSIONS = frozenset(
    [
        "2.1.216",
        "2.1.220",
        "2.1.223",
        "2.1.226",
        "2.1.233",
        "2.1.238",
        "2.1.263",
    ]
)

SUPPORTED_CODEX_CLI_VERSIONS = frozenset(
    [
        "0.146.0-alpha.3.1",
    ]
)


def _supported_label(supported):
    return ", ".join(sorted(supported)) if supported else "（空集）"


def check_claude_version(version):
    """校验 Claude 侧检测键。不在支持集 → `SchemaVersionError`（exit 4）。

    返回原值（便于调用方直接落 `source_version`）。
    """
    if not isinstance(version, str) or not version:
        raise exit_codes.SchemaVersionError(
            "Claude 日志缺少 schema 版本检测键 `{0}`（未声明版本 → 按纪律不解析）。"
            "期望取值集合：{1}".format(CLAUDE_VERSION_KEY_PATH, _supported_label(SUPPORTED_CLAUDE_VERSIONS))
        )
    if version not in SUPPORTED_CLAUDE_VERSIONS:
        raise exit_codes.SchemaVersionError(
            "未识别的 Claude schema 版本：{0!r}（检测键路径 `{1}`）。"
            "已支持版本集合：{2}。"
            "按纪律**不按最宽松规则静默解析**——请核对日志格式或为本版本补充支持集。".format(
                version, CLAUDE_VERSION_KEY_PATH, _supported_label(SUPPORTED_CLAUDE_VERSIONS)
            )
        )
    return version


def check_codex_cli_version(cli_version):
    """校验 Codex 侧检测键。不在支持集 → `SchemaVersionError`（exit 4）。"""
    if not isinstance(cli_version, str) or not cli_version:
        raise exit_codes.SchemaVersionError(
            "Codex 日志缺少 schema 版本检测键 `{0}`（未声明版本 → 按纪律不解析）。"
            "期望取值集合：{1}".format(CODEX_VERSION_KEY_PATH, _supported_label(SUPPORTED_CODEX_CLI_VERSIONS))
        )
    if cli_version not in SUPPORTED_CODEX_CLI_VERSIONS:
        raise exit_codes.SchemaVersionError(
            "未识别的 Codex schema 版本：{0!r}（检测键路径 `{1}`）。"
            "已支持版本集合：{2}。"
            "按纪律**不按最宽松规则静默解析**——请核对日志格式或为本版本补充支持集。".format(
                cli_version, CODEX_VERSION_KEY_PATH, _supported_label(SUPPORTED_CODEX_CLI_VERSIONS)
            )
        )
    return cli_version
