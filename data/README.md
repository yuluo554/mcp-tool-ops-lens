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
| 失败判定字段精确语义 | is_error 三态（True / False / **字段缺失**）+ `toolUseResult.interrupted` | ✅ **已核对**（2026-10-16 本机实测，结论见第五节 A） | 本机 94 个 jsonl / 45.3 MB |
| 跨版本格式漂移 | Claude Code 顶层 `version` 字段；Codex `session_meta.cli_version` | ✅ **已核对**（检测键确定，见第五节 A/D） | 本机实测（Claude 7 个版本号） |
| settings.json 白名单键位 | `permissions.allow`（**`env` 含活体凭据，禁读**） | ✅ **已核对**（见第五节 C） | 本机实测 |
| Codex token 归因可得性 | `event_msg/token_count` 仅会话累计 / 整轮粒度 | ✅ **已核对：按工具调用归因不可得**（见第五节 D） | 本机 220 个 rollout |

## 三、合成数据纪律

1. **假 server 名白名单**：合成日志只用虚构名，如 `mcp__fake-server__tool`、`mcp__fake-server__search` 等以 `fake-server` 为 server 段的命名；**不得混入真实 server 名**。
2. **真值植入**：真值程序化标注——生成器在产出日志的同时产出真值清单（已知哪个 server 的失败率是多少、哪条记录应归为超时/权限拒绝/参数错误/内容拒绝），基准对账以真值清单为准。
3. **覆盖度口径**：基准套件按 server 维度（高失败率/中失败率/低失败率/正常重试型）与失败模式维度（超时/权限拒绝/参数错误/内容拒绝各至少覆盖）列最低覆盖项，写进 manifest；防偏科。
4. **真实会话日志不入仓**：`.gitignore` 已排除；示例报告一律基于合成数据生成。

## 四、数值口径纪律（一处定义）

以下口径**仅在本节定义一次**，引擎、真值、报告与文档引用必须同源，不得在任何注记/代码注释里手写第二份表述：

- **失败判定**：以 M1 核对后的字段语义为准（✅ 已于 2026-10-16 核对，结论见第五节 E）。
- **重试识别**：同 server + 同 tool 在短时间窗内的连续失败后再次调用，记为一次重试；具体窗口值进配置文件，不写死在代码。
- **耗时口径**：以日志中工具调用耗时字段（如 lastToolDuration / item_completed 计时）为准；缺失耗时的样本在均值计算中剔除并在报告中说明样本量。
- **token 开销口径**：单次工具调用的 message.usage token 数；聚合维度分 server 级与 tool 级两级。

## 五、M1 字段语义核对结论（2026-10-16 本机实测，核对主体：94 个 Claude jsonl + 220 个 Codex rollout）

> 本节是"未核对字段不进计算路径"（模块 1/2/3 共用的门控依据）的**唯一出处**。
> 下列结论均为**本机实测计数**，不是文档推测；观测脚本不入仓（一次性只读探针），结论可按下述计数口径复跑复核。

### A. Claude Code 失败判定：`is_error` 是三态，不是布尔（**本项推翻题目文档的默认假设**）

题目文档与 plan/00 原假设"失败判定 = `is_error` 标志"。实测**不成立**，必须按下表三态处理：

| `is_error` 取值 | 语义 | 本机计数（10 个最大 jsonl 抽样） |
|---|---|---|
| `true` | **确定失败** | 78 |
| `false` | **确定成功** | 335 |
| **字段缺失（`None`）** | **未声明成败**——不等于成功 | **409**（约占 50%） |

- **缺失态不是成功**：对 `is_error` 缺失的 724 条结果做错误文本模式匹配，**108 条（14.9%）命中**错误类模式（error / exception / traceback / denied / permission / timeout / refused / invalid / failed / `exit code [1-9]`）；而对 `is_error=false` 的 380 条，仅 97 条命中（多为工具正常输出里恰好含这些词）。
- **结论（进计算路径的口径）**：失败判定**只认 `is_error is True`**；`is_error is False` 记成功；**字段缺失一律记 `unknown`，不计入成功率分子也不计入分母**（或单列"未声明"计数），**绝不默认为成功**——默认成功会把 14.9% 的真实失败静默洗成成功，直接污染模块 2 的失败率与模块 4 的删换建议。
- **次生信号（可用但不得当主判据）**：顶层 `toolUseResult.interrupted`（布尔）标记中断；`toolUseResult.stderr` 非空是弱信号。二者进 `notes` 供审计，**不改写 `is_error` 的判定**。
- 配套：本结论的 `unknown` 态必须**在报告里显式可见**（否则"未声明"看起来像"没问题"）。

### B. Claude Code token 与耗时口径

- **token 粒度 = 每条 assistant 消息级**：`message.usage`（键集含 `input_tokens` / `output_tokens` / `cache_creation_input_tokens` / `cache_read_input_tokens` / `service_tier` 等）。实测**携带 `tool_use` 的 613 条 assistant 消息，613 条都带 `usage`** → **覆盖率 100%**，且 `tool_use` 与 assistant 消息**实测 1:1**（1105 条消息，每消息恰 1 个 `tool_use`）。
- **口径推论（重要）**：token 是**在 assistant 消息上**、不在工具结果上——即"该次工具调用**所在轮次**的 token 开销"，**不是工具自身耗时消耗的 token**。故模块 2/4 的一切 token 表述必须以"**归属调用轮次**"为准，报告中不得写成"该工具消耗了 N token"（**这是"数值口径不一致 = 直接比就是造假结论"家族的实例**）。
- **`input_tokens` 与缓存分开记**：`cache_read_input_tokens` / `cache_creation_input_tokens` 单列，**不并入** `input_tokens` 做"总开销"（否则按轮次累加会重复计数）。
- **单次调用耗时：日志内不可得**。Claude jsonl 顶层**无** `duration*` 字段（全抽样只见 `system.durationMs` 共 6 条，非工具耗时）。可用耗时字段仅在 `~/.claude.json` 的项目级 **`lastToolDuration`（毫秒，整数；本机实测 4361 / 88811 / 107212）**——**只是"最后一次工具的耗时"，非按工具聚合**。→ 模块 2 的"平均耗时"**首期按"不可得"处理**（报告显式标注样本不可得），**不得用 lastToolDuration 冒充按工具耗时**；该字段只作项目级参考项单列。

### C. `~/.claude/settings.json`：白名单键位 + **隐私红线（凭据在文件里）**

- 实测顶层键：`attribution` / `defaultMode` / `effortLevel` / `enabledPlugins` / **`env`** / `hooks` / `permissions` / `model` / `statusLine` / `theme` 等。
- **MCP 工具白名单实际在 `permissions.allow`**（形如 `mcp__<server>__<tool>`），**不是**题目文档写的"mcpServers 白名单"；`allowedTools` / `enabledMcpjsonServers` 在 settings.json 中**不存在**（后者在 `~/.claude.json` 的项目块里）。
- **❗隐私红线（实测发现，必须落成硬约束）**：`settings.json` 的 **`env` 块内含活体凭据**（实测含 `ANTHROPIC_AUTH_TOKEN` 等）。**解析器只准按显式键白名单读取**（`permissions.allow`、`enabledPlugins`），**禁止整体 `json.load` 后外传/落盘/进报告任何 `env` 内容**；`env` 属于**永不读取**的键（比"读了不打印"更强的口径）。此条进 `.gitignore` 之外的**代码级守卫**（M2 落成测试）。

### D. Codex rollout：结构确认 + **按工具 token 归因不可得**

- 文件 `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，每行 `{type, payload, timestamp, ordinal}`。
- 实测 type 分布：`response_item`（`reasoning` / `function_call` / `function_call_output` / `custom_tool_call` / `custom_tool_call_output` / `message`）、`event_msg`（`token_count` 1021 条 / `item_completed` 887 / `task_started` / `task_complete` / `turn_aborted`）、`turn_context`、`world_state`、`compacted`、`session_meta`（每文件 1 条）。
- **版本检测键**：`session_meta.cli_version`（实测 `0.146.0-alpha.3.1`）。
- **tool 名分布**：`exec` / `js` / `wait` / `shell_command` / `view_image` / `apply_patch` 等（**无 `mcp__<server>__<tool>` 前缀命名**——Codex 侧 MCP 工具命名与 Claude 侧不同，首期如实记录、不强行套用 Claude 的 server 解析规则）。
- **成败信号：无显式 `is_error`**。可得的替代信号是**文本模式**：输出内 `Exit code: N`（实测 458 条 0 / 39 条 1 / 2 条 124）与 `Wall time: N seconds`（1413/1518 条含）。`custom_tool_call.status` 实测**恒为 `completed`**（2603/2603）→ **不能当成败判据**（"取值恒为哑值"形态，正是"对账单元自带结论"要防的坑）。→ Codex 侧失败判定 = **规则匹配 `Exit code` 非 0**（归入模块 3 模式表，标"已核对样例"后生效），**无该字段者记 `unknown`**。
- **token 粒度 = 会话/轮级，不可按工具归因**：`event_msg/token_count` 的 `info.total_token_usage` / `last_token_usage`（含 `input_tokens` / `cached_input_tokens` / `output_tokens` / `reasoning_output_tokens` / `total_tokens`）是**会话累计或整轮差值**，与具体某次 `function_call` 无绑定关系（且 `reasoning` 类 response_item 大量存在）。→ **模块 2 的 token 维度首期只对 Claude Code 声明覆盖**；Codex 侧 token 单列"会话级参考"，并按 `source` 标注来源，**绝不把会话级 token 摊到单次工具调用上**。
- **耗时**：`Wall time: N seconds` 可用（文本模式，1413/1518 条命中）→ Codex 侧耗时**可比 Claude 侧更完整**；但两侧口径不同源，报告中**分源呈现，不混算均值**。

### E. 由此固化进计算路径的口径（模块 1→2→3 共用，一处定义）

| 口径 | 生效定义 | 三态/缺失处理 |
|---|---|---|
| 调用记录 | Claude：assistant 消息内 `tool_use` 块（1 消息 = 1 块，实测）；Codex：`function_call` / `custom_tool_call` | — |
| 成败 | Claude：**只认 `is_error is True` 为失败**，`False` 为成功，**缺失 = `unknown`**；Codex：`Exit code` 非 0 为失败，无该文本 = `unknown` | `unknown` 单列，**不进成功/失败分子分母** |
| 工具标识 | Claude：`mcp__<server>__<tool>` 拆 server/tool；非 `mcp__` 前缀的内置工具 → `server=<builtin>` | Codex：原样记录工具名，**不套 Claude 前缀规则** |
| token | Claude：`message.usage`，按**调用轮次**归属，缓存两项单列；Codex：**不按工具归因**（会话级另列） | 缺失 = `unknown` 并在报告标注样本量 |
| 耗时 | Claude：**按工具不可得**（只项目级 `lastToolDuration` 作参考）；Codex：`Wall time` 文本 | 不可得 = 显式标注，**不代入均值** |
| 重试 | 见第四节（短时间窗内同 server+同 tool 连续失败后再调用） | 窗口值进配置文件 |

**未覆盖/不承诺项（如实登记）**：Codex 按工具 token、Claude 按工具耗时、`is_error` 缺失态的真值（本机无法证伪"缺失=成功"的残余可能，故一律 `unknown` 而非二分）。

