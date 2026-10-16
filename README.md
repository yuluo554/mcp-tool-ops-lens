# mcp-tool-ops-lens

> **你往 agent 里加了十几个 MCP server，但哪个失败率最高？每次调用吃多少 token？哪个纯属拖慢 agent？**
> ——从本机会话日志统计每个 MCP server / 工具的调用、失败、token 开销，给出可执行的删/换建议。

纯本地 Python CLI：**零上传、零遥测、零第三方依赖、不使用任何模型**。统计是确定性计数，归因是规则匹配。

> 状态：**v0.1.0 开发中**（M0 计划与骨架已完成；五个模块的实现里程碑见 `plan/05-里程碑.md`）。
> 管理侧工具已有很多（agent-deck 等），"可靠性 + 开销归因"侧近乎空白——这是本项目的定位。

## 为什么需要它

AI 编程 agent 重度依赖 MCP server 与内置工具，但用户对这些工具的实际表现几乎处于盲区：失败了没人统计、浪费了多少上下文 token 也没人数。

- 上下文开销是真实痛点：社区原话是"还没输入一条消息，就已经烧掉 16k token 上下文"。
- 失败率也已被量化：公开研究（91,747 次生产环境 agent 工具调用）报告 **4.12% 硬失败率**，且上下文预算超支是最高频的失败模式。

本项目把这两件事合成一个 CLI：**按 server / tool 归因失败率与上下文开销**，并给出带口径与样本量的删/换建议。

## 安装

```bash
git clone <本仓库地址>
cd 10-16-2-mcp-tool-ops-lens
pip install -e ".[dev]"
```

要求 Python ≥ 3.8，运行时**零第三方依赖**（`dev` extra 只装 pytest，用于跑测试）。

## 使用

```bash
# 1) 解析本机构建统一事件流（只读，不修改任何配置）
opslens scan --home ~ --out events.json

# 2) 按 server / tool 两级聚合（调用数 / 失败率 / token 开销）
opslens aggregate --events events.json --out agg.json

# 3) 对失败调用做规则匹配分类（超时 / 权限拒绝 / 参数错误 / 内容拒绝 / 其他）
opslens attribute --events events.json --out attr.json

# 4) 产出删换建议报告（Markdown + HTML + JSON 三份，断网可开）
opslens report --events events.json --out examples/

# 5) 真值基准对账（引擎输出 vs 合成日志植入的真值）
opslens bench
```

`python -m opslens <命令>` 与上面的 `opslens <命令>` 等价（两条通路都可用）。

选项：
- `--home <目录>`：数据源根目录，缺省为当前用户 home。**测试与演示请显式传临时目录**，避免误扫真实会话。
- `--rules-dir <目录>`：规则包目录，缺省 `data/rules/`。
- `--only <套件>`：`bench` 只跑指定套件。

## 退出码

| 码 | 语义 |
|---|---|
| 0 | 成功 |
| 1 | 运行完成但**检出问题**（如命中"建议移除"、基准未达标）——不是跑挂 |
| 2 | 用法错误 / 未知名 / 参数非法 |
| 3 | 阶段未就绪（当前骨架期占位，不伪造空结果；随模块落地退役） |
| 4 | 数据不可用（数据源目录不存在 / schema 版本不识别） |

## 数据来源（只读）

| 工具 | 路径 | 用于 |
|---|---|---|
| Claude Code | `~/.claude/projects/*/*.jsonl` | 工具调用事件、成败、token |
| Claude Code | `~/.claude.json` | mcpServers 清单、项目级指标 |
| Claude Code | `~/.claude/settings.json` | MCP 工具白名单（**只读 `permissions.allow`**） |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | 工具调用事件、成败、耗时 |

**首期只声明 Claude Code + Codex**；其他工具（Cursor 等）属扩展项，未实现。

## 隐私

- **零上传、零遥测**：代码内无任何网络模块 import（有守门测试锁定），断网可跑。
- **不修改用户配置**：纯只读分析 + 建议，不自动删改任何 MCP 配置。
- **真实会话日志不入仓**：仓库内只含基于虚构 `fake-*` server 名的合成数据。
- `~/.claude/settings.json` 的 `env` 块可能含凭据，解析器**只按显式键白名单读取，`env` 永不读取**。

## 项目文档

| 文档 | 内容 |
|---|---|
| `plan/00-README总览.md` | 索引、决策记录、承诺-证据台账 |
| `plan/01-题目文档.md` | 题目定稿（五模块、评分口径、边界） |
| `plan/02-架构与技术选型.md` | 分层架构、统一 IR、确定性与隐私设计 |
| `plan/03-模块详设.md` | 五模块详设与指标口径（唯一出处） |
| `plan/04-数据计划.md` | 数据资产台账、合成数据规格、真值植入 |
| `plan/05-里程碑.md` | 里程碑与 DoD（每周可演示） |
| `plan/06-交付对标.md` | 评分标准对标、待定决策表 |
| `data/README.md` | 依据查证、**字段语义实测结论**、数值口径纪律 |

## 开发

```bash
pytest -q
```

纪律（均有守门测试）：零第三方依赖、零出网、无时钟无随机、确定性写盘（同输入逐字节一致）、
阈值全部来自 `data/rules/*.json`（代码零阈值字面量）。

## 许可

MIT
