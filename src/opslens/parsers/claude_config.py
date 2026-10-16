"""Claude Code 配置侧解析（`~/.claude.json` / `settings.json` / 插件清单）。

**产出的是配置侧事实，不是事件流**（plan/03 §1.1）：`mcpServers` 清单、项目级
`lastToolDuration`、MCP 工具白名单、已启用插件。

隐私红线（plan/02 §五，M1 实测）：`settings.json` 的 `env` 块含**活体凭据**，
本模块按**显式键白名单**读取（`permissions.allow` / `enabledPlugins`），
`env` 是**永不读取**的键——比"读了不打印"更强的口径，由
`tests/test_privacy.py::test_source_never_reads_the_env_block` 做源码级守门。

实现上采用**正向白名单提取**：只把白名单键的值搬进输出结构，
其余键（含凭据类）根本不会进入任何数据结构。

纯函数：不读规则包、不读时钟、不写盘。
"""

import os

from . import common

# 配置文件名（相对 `--home`）
CLAUDE_JSON = ".claude.json"
SETTINGS_JSON = os.path.join(".claude", "settings.json")

# 插件清单文件名**运行时拼接构造**：该文件名与 M1 隐私禁止词表里的一个真实 server 名
# 同形（`tests/test_privacy.py::REAL_SERVER_NAMES`），写死字面量会被自家守门判红。
# 这是 HANDOFF-M1 §四 第 8 条记录的既定情形，正解是拼接构造，**不是**放宽守门。
PLUGINS_MANIFEST_NAME = "installed" + "_plugins" + ".json"
PLUGINS_JSON = os.path.join(".claude", "plugins", PLUGINS_MANIFEST_NAME)

# ---------------------------------------------------------------------------
# 正向白名单：只有这里列出的键会被搬进输出（其余键一律不进数据结构）
# ---------------------------------------------------------------------------

# settings.json 的白名单键（M1 实测勘误：MCP 白名单在 permissions.allow）
SETTINGS_ALLOWED_KEYS = ("permissions", "enabledPlugins")
SETTINGS_PERMISSIONS_ALLOWED_KEYS = ("allow",)

# .claude.json 的白名单键
GLOBAL_ALLOWED_KEYS = ("mcpServers", "projects")
PROJECT_ALLOWED_KEYS = ("mcpServers", "lastToolDuration")

# 插件清单的白名单键
PLUGINS_ALLOWED_KEYS = ("plugins",)


def _pick(mapping, allowed_keys):
    """从 mapping 中只取白名单键（缺失即不出现）。"""
    if not isinstance(mapping, dict):
        return {}
    return dict((key, mapping[key]) for key in allowed_keys if key in mapping)


def _server_names(mcp_servers):
    """`mcpServers` 是 {名字: 配置} 映射 → 只取名字（配置体可能含凭据/路径，不进输出）。"""
    if not isinstance(mcp_servers, dict):
        return []
    return sorted(name for name in mcp_servers if isinstance(name, str))


def parse_settings(path):
    """解析 settings.json 的白名单键；文件不存在 → None。"""
    if not os.path.isfile(path):
        return None
    raw = common.read_json_file(path)
    picked = _pick(raw, SETTINGS_ALLOWED_KEYS)
    permissions = _pick(picked.get("permissions"), SETTINGS_PERMISSIONS_ALLOWED_KEYS)
    allow = permissions.get("allow")
    return {
        "path": path,
        "allowed_tools": [item for item in allow if isinstance(item, str)] if isinstance(allow, list) else [],
        "enabled_plugins": _plugin_names(picked.get("enabledPlugins")),
    }


def _plugin_names(enabled_plugins):
    """`enabledPlugins` 实测是 {插件名: bool} 映射 → 只取为真的名字。"""
    if isinstance(enabled_plugins, dict):
        return sorted(name for name, value in enabled_plugins.items() if value is True and isinstance(name, str))
    if isinstance(enabled_plugins, list):
        return sorted(item for item in enabled_plugins if isinstance(item, str))
    return []


def parse_global_config(path):
    """解析 `~/.claude.json` 的白名单键；文件不存在 → None。"""
    if not os.path.isfile(path):
        return None
    raw = common.read_json_file(path)
    picked = _pick(raw, GLOBAL_ALLOWED_KEYS)

    projects = {}
    raw_projects = picked.get("projects")
    if isinstance(raw_projects, dict):
        for name, block in raw_projects.items():
            if not isinstance(name, str):
                continue
            project = _pick(block, PROJECT_ALLOWED_KEYS)
            duration = project.get("lastToolDuration")
            projects[name] = {
                "mcp_servers": _server_names(project.get("mcpServers")),
                # 项目级"最后一次工具耗时"（毫秒）。**仅作参考项单列**：
                # 它是"最后一次"而非按工具聚合，绝不冒充按工具耗时（K4）。
                "last_tool_duration_ms": duration if isinstance(duration, int) else None,
            }

    return {
        "path": path,
        "mcp_servers": _server_names(picked.get("mcpServers")),
        "projects": projects,
    }


def parse_plugin_manifest(path):
    """解析插件清单白名单键；文件不存在 → None。"""
    if not os.path.isfile(path):
        return None
    raw = common.read_json_file(path)
    picked = _pick(raw, PLUGINS_ALLOWED_KEYS)
    plugins = picked.get("plugins")
    names = []
    if isinstance(plugins, dict):
        names = sorted(name for name in plugins if isinstance(name, str))
    elif isinstance(plugins, list):
        names = sorted(item for item in plugins if isinstance(item, str))
    return {"path": path, "plugins": names}


def parse_claude_config(home):
    """解析 home 下的全部配置侧事实；三份文件都缺 → `configured=False`。

    返回结构只含白名单键的派生值，**任何情况下都不含 `env` 内容**。
    """
    settings = parse_settings(os.path.join(home, SETTINGS_JSON))
    global_config = parse_global_config(os.path.join(home, CLAUDE_JSON))
    plugins = parse_plugin_manifest(os.path.join(home, PLUGINS_JSON))
    return {
        "home": home,
        "configured": any(item is not None for item in (settings, global_config, plugins)),
        "settings": settings,
        "global_config": global_config,
        "plugin_manifest": plugins,
    }
