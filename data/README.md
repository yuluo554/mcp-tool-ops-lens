# data/README.md · 数据与查证记录

仓库：`10-16-2-mcp-tool-ops-lens`（MCP/工具调用失败率与上下文开销归因 CLI）。基准日：**2026-10-15**。

## 一、依据查证记录（三态：✅ 已核对 / ⬜ 待核对）

| 依据 | 内容 | 状态 | 渠道 |
|---|---|---|---|
| 痛点证据 1 | HN《Show HN: Unclog – find and fix Claude Code context bloat》（id 47822779）作者原话："kept adding MCPs, skills, hooks... found I was burning 16k tokens of context before typing a single message" | ✅ | HN（item id 47822779） |
| 痛点证据 2 | HN《I Cut my Agent Tokens By 50%》（id 50047627） | ✅ | HN（item id 50047627） |
| 量化研究 | BenjisCollector/agent-failure-study 自述实测："91,747 production coding-agent tool calls: 4.12% hard failure rate, context budget overrun is the top mode" | ✅（引用其自述，不二次复测） | GitHub 仓库自述 |
| 开源空白 | 7 条检索式（下表） | ⬜ 软论据（记检索式与基准日，可回溯复跑） | gh api，基准日 2026-10-15 |

### 开源空白检索式留档（gh api，基准日 2026-10-15）

| 检索式 | 命中情况 |
|---|---|
| `MCP server health check token overhead` | 0 |
| `MCP tool call error rate local` | 0 |
| `MCP context overhead measurement` | 0 |
| `tool call failure rate analysis agent` | total=1（agent-failure-study 0★，仅分析非工具） |
| `MCP tool reliability observability` | 最高 Harshit-J004/toolguard **15★** |
| `claude code session token waste diagnosis` | 0 |
| 管理/同步侧对照 | agent-deck 1085★、bridle 440★、claude-code-tool-manager 382★、mcp-linker 341★（已饱和）；bloat 清理侧 unclog 36★（只清理不做失败率归因） |

**判定：可靠性+开销归因侧最大仅 15★，近乎空白**（软论据，论据强度低于原文直连类硬锚点）。

## 二、数据源可获取性记录（本机实测，基准日 2026-10-15）

| 数据源 | 路径 | 关键字段 | 状态 |
|---|---|---|---|
| Claude Code 全局配置 | `~/.claude.json`（66KB） | mcpServers（按 project 分列）、lastSessionMetrics、costUSD、inputTokens/outputTokens、usageCount、lastToolDuration | ✅ |
| Claude Code 会话日志 | `~/.claude/projects/*/*.jsonl` | tool_use 记录工具名（含 `mcp__<server>__<tool>` 前缀命名，可按 server 聚合）、tool_result 成败、message.usage token 数 | ✅ |
| Claude Code 设置 | `~/.claude/settings.json` | MCP 工具白名单 | ✅ |
| 插件清单 | `~/.claude/plugins/installed_plugins.json` | 插件列表 | ✅ |
| Codex 会话日志 | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | session_meta / response_item / item_completed 含 token 数 | ✅ |
| 失败判定字段精确语义 | is_error 标志 / 异常文本模式 | — | ⬜ 待核对（M1 数据先行阶段逐字段核对后入库，核对结论回填本表） |
| 跨版本格式漂移 | 各工具不同版本日志格式 | — | ⬜ 待核对（解析器带 schema 版本检测） |

## 三、合成数据纪律

1. **假 server 名白名单**：合成日志只用虚构名，如 `mcp__fake-server__tool`、`mcp__fake-server__search` 等以 `fake-server` 为 server 段的命名；**不得混入真实 server 名**。
2. **真值植入**：真值程序化标注——生成器在产出日志的同时产出真值清单（已知哪个 server 的失败率是多少、哪条记录应归为超时/权限拒绝/参数错误/内容拒绝），基准对账以真值清单为准。
3. **覆盖度口径**：基准套件按 server 维度（高失败率/中失败率/低失败率/正常重试型）与失败模式维度（超时/权限拒绝/参数错误/内容拒绝各至少覆盖）列最低覆盖项，写进 manifest；防偏科。
4. **真实会话日志不入仓**：`.gitignore` 已排除；示例报告一律基于合成数据生成。

## 四、数值口径纪律（一处定义）

以下口径**仅在本节定义一次**，引擎、真值、报告与文档引用必须同源，不得在任何注记/代码注释里手写第二份表述：

- **失败判定**：以 M1 核对后的字段语义为准（⬜ 当前待核对，核对前任何实现不得进入计算路径）。
- **重试识别**：同 server + 同 tool 在短时间窗内的连续失败后再次调用，记为一次重试；具体窗口值进配置文件，不写死在代码。
- **耗时口径**：以日志中工具调用耗时字段（如 lastToolDuration / item_completed 计时）为准；缺失耗时的样本在均值计算中剔除并在报告中说明样本量。
- **token 开销口径**：单次工具调用的 message.usage token 数；聚合维度分 server 级与 tool 级两级。
