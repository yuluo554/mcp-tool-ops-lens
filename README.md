# mcp-tool-ops-lens

[![CI](https://github.com/yuluo554/mcp-tool-ops-lens/actions/workflows/ci.yml/badge.svg)](https://github.com/yuluo554/mcp-tool-ops-lens/actions/workflows/ci.yml)

> **你往 agent 里加了十几个 MCP server，但哪个失败率最高？每次调用吃多少 token？哪个纯属拖慢 agent？**
> ——从本机会话日志统计每个 MCP server / 工具的调用、失败、token 开销，给出可执行的删/换建议。

纯本地 Python CLI：**零上传、零遥测、零第三方依赖、不使用任何模型**。统计是确定性计数，归因是规则匹配。

> 状态：**✅ v0.1.0 已发布**（[Release](https://github.com/yuluo554/mcp-tool-ops-lens/releases/tag/v0.1.0) ·
> CI 四矩阵绿）。六个里程碑 M0–M6 全部完成；发布留档见 [`plan/RELEASE-M6.md`](plan/RELEASE-M6.md)。
> 五个子命令**全部落地**：`scan`（解析）、`aggregate`（两级统计）、`attribute`（失败分类）、`report`（删换建议报告 MD/HTML/JSON）、`bench`（真值基准对账）。
>
> 管理侧工具已有很多（agent-deck 等），"可靠性 + 开销归因"侧近乎空白——这是本项目的定位。

## 为什么需要它

AI 编程 agent 重度依赖 MCP server 与内置工具，但用户对这些工具的实际表现几乎处于盲区：失败了没人统计、浪费了多少上下文 token 也没人数。

- 上下文开销是真实痛点：社区原话是"还没输入一条消息，就已经烧掉 16k token 上下文"。
- 失败率也已被量化：公开研究（91,747 次生产环境 agent 工具调用）报告 **4.12% 硬失败率**，且上下文预算超支是最高频的失败模式。

本项目把这两件事合成一个 CLI：**按 server / tool 归因失败率与上下文开销**，并给出带口径与样本量的删/换建议。

## 安装

```bash
git clone <本仓库地址>
cd mcp-tool-ops-lens
python -m venv .venv
# Windows: .venv\Scripts\activate   /  Linux、macOS: source .venv/bin/activate
python -m pip install -U pip        # Python 3.8 自带 pip 20.2.3 无法可编辑安装 pyproject-only 项目
python -m pip install -e ".[dev]"
```

要求 Python ≥ 3.8，运行时**零第三方依赖**（`dev` extra 只装 pytest，用于跑测试）。
用 `python -m pip`（而非裸 `pip`）以便 venv 内安装；**已激活 venv 时不要用 Windows 的 `py`
启动器**——`py` 走独立 launcher，会把包装到系统 Python 而非 venv。

## 使用

```bash
# 1) 解析本机构建统一事件流（只读，不修改任何配置）—— M2 已可用
opslens scan --home ~ --out events.json

# 2) 按 server / tool 两级聚合（调用数 / 失败率 / token 开销）—— M3 已可用
opslens aggregate --events events.json --out agg.json

# 3) 对失败调用做规则匹配分类（超时 / 权限拒绝 / 参数错误 / 内容拒绝 / 其他）—— M3 已可用
opslens attribute --events events.json --out attr.json

# 4) 产出删换建议报告（Markdown + HTML + JSON 三份，断网可开）—— M5 已可用
opslens report --events events.json --out examples/

# 5) 真值基准对账（引擎输出 vs 合成日志植入的真值）—— M4 已可用
opslens bench

# 5b) 只跑双基线（解析对账 F1 + e2e 双跑逐字节一致），里程碑收尾复跑
opslens bench --check
```

`python -m opslens <命令>` 与上面的 `opslens <命令>` 等价（两条通路都可用）。

选项：
- `--home <目录>`：数据源根目录，缺省为当前用户 home。**测试与演示请显式传临时目录**，避免误扫真实会话。
- `--out <文件>`：`scan` / `aggregate` / `attribute` / `bench` 的产物输出路径（JSON）；省略则只打印摘要。
- `--out <目录>`：`report` 的产物输出**目录**（写 `report.json` + `report.md` + `report.html` 三份）。
- `--events <文件>`：`scan` 产出的事件流 JSON（`aggregate` / `attribute` / `report` 的输入）。
- `--rules-dir <目录>`：规则包目录，缺省 `data/rules/`。
- `--only <套件>`：`bench` 只跑指定套件（未知名 → 退出码 2）。
- `--data-dir <目录>`：`bench` 的合成数据目录，缺省 `data/synthetic/`。

### 聚合与归因（M3）口径要点

| 项 | 口径 | 落点 |
|---|---|---|
| 成败三态 | `ok` / `error` / `unknown`；**三者相加 = 总数**（对账等式，锁进测试） | `aggregate.py` |
| 失败率 | 分母 = `ok + error`，**不含 `unknown`**；分母为 0 → `null` + `insufficient_data=true` | `aggregate.py` |
| token | 四项（`input`/`output`/`cache_read`/`cache_creation`）**分列**；`token_samples` / `token_missing` 单列；均值名带 `turn_` 前缀 | `aggregate.py` |
| 耗时 | Claude 侧 `null` + `duration_available=false`（**不用 `lastToolDuration` 冒充**）；Codex 侧取 `Wall time`，两侧不混算 | `aggregate.py` |
| 重试 | 同 server + 同 tool 在**时间窗**内失败后再次调用记一次；窗口值来自 `params.json`（不写死） | `aggregate.py` |
| 两级维度 | server 级 `GROUP BY source, server`；tool 级 `GROUP BY source, server, tool`；**两级都输出 `unknown` 计数** | `aggregate.py` |
| 失败分类 | `timeout` / `permission_denied` / `invalid_args` / `content_refusal` / `other` | `attribute.py` |
| 规则门控 | `status=="verified"` **且** `verified_samples` 非空才进计算路径；未生效规则落 `other` 并**列出原因** | `config.py` → `attribute.py` |
| 匹配面 | **只在 `error_text` 上匹配**（宽模式会在成功记录的正常输出上误命中） | `attribute.py` |

**口径唯一性守门**：AST 断言除法运算（`BinOp(Div)`）只出现在 `aggregate.py` / `attribute.py` / `bench.py` / 真值生成器
（生成器须与引擎独立，否则真值沦为"引擎自证"；基准算的是**解析质量指标** precision/recall/F1，不是域口径的第二份计算）——防报告层或 CLI 层出现第二份比率计算。

### 真值基准（M4）

`opslens bench` 拿 `data/synthetic/` 的**冻结合成数据**跑一遍引擎（解析 → 聚合 → 归因），
把引擎输出与 `truth.json` 的**植入期望**逐维度对账，差异**逐条列出**（维度 / 键 / 期望 / 实际）：

| 层 | 套件 | 对账什么 |
|---|---|---|
| 样本驱动 | `S-THREE-STATE` / `S-FAILURE-RATE` / `S-RETRY-COUNT` / `S-TOKEN` / `S-DURATION` / `S-TWO-LEVEL` | 三态计数、失败率与分子分母、重试、token 分列、耗时口径、两级维度 rollup |
| 规则驱动 | `R-CATEGORY-DIST` / `R-RULE-GATE` / `R-MATCH-AUDIT` | 失败分类分布、规则生效门控、命中可审计 |
| 覆盖声明 | `C-MANIFEST-COVERAGE` | 消费 `manifest.json` 的逐维度"总数/采样数"双登记 + 非穷举声明 |
| 双基线 | `B-PARSE-RECONCILE` / `B-E2E-DETERMINISM` | 解析对账基线（计数级 F1 = 1）+ e2e 双跑逐字节一致 |

三条纪律：

- **观测由基准运行时实算**（K12）：引擎输出是**重新扫描 + 重新聚合 + 重新归因**得到的，
  与 `truth.json` 无数据通路——真值只提供期望值（真值库出现 `observed_*` 字段会被守门判红）。
- **每套件配可证伪探活**：把输入**故意弄坏**（如把 `is_error=True` 判成 `ok`、把未生效规则塞进计算路径），
  同一套 check 必须报出差异。探活**未变红 = 该套件是假门**，基准自判未达标。
- **"未启用"不冒充通过**：无生效规则 / 无失败样本等空分母情形 → 套件 `not_enabled=true` + notes + **退出码 1**。

退出码：`0` 达标 / `1` 未达标（差异、未启用、或探活未变红）/ `2` 用法与未知名（如 `bench --only NOPE`）。

### 删换建议报告（M5）

`opslens report --events events.json --out <目录>` 产出**三份**产物（示例见
[`examples/report.md`](examples/report.md) / [`examples/report.html`](examples/report.html)，
基于合成数据，真实日志不入仓）：

| 产物 | 格式 | 说明 |
|---|---|---|
| `report.json` | JSON（机读） | **单一渲染源**：所有结论的唯一结构化出处 |
| `report.md` | Markdown（人读） | 由 `report.json` 渲染 |
| `report.html` | HTML（人读） | 由 `report.json` 渲染；**内联 CSS、零外链**，断网可开 |

**"两格式内容一致"是结构性质**：MD 与 HTML 都从同一份 `report.json` 渲染，
不是两份各写各的再人工比对。

报告必含五节：① 数据来源与覆盖声明（扫了哪些路径 / 哪些源 / schema 版本）；
② **`unknown` 与样本缺失独立分区**（不混入统计）；③ 建议清单（每条附**口径 + 阈值取值 + 分子/分母 + 样本量**）；
④ 未生效规则清单（含原因）；⑤ 定位宣言 + **"建议仅供参考，不自动修改配置"**。

建议类型与触发（阈值全部可配，落 `data/rules/thresholds.json`）：

| 建议 | 触发 | 必附证据 |
|---|---|---|
| `remove_candidate` | `failure_rate ≥ T_fail` **且** `calls_total ≥ N_min` | 失败率 + 分子/分母 + 样本量 |
| `investigate` | `T_warn ≤ failure_rate < T_fail` 且样本量足够 | 同上 |
| `cost_heavy` | `turn_token_avg ≥ T_tok` **且** `token_samples ≥ N_tok` | 均值 + 参与样本数 + 缺失数 |
| `low_signal` | 样本不足 | **降级"数据不足"，不出建议** |

三条纪律（均有守门测试）：

- **渲染层零判定**（AST 守门）：`report/` 内**无 `BinOp(Div)`**、**不 import 聚合/归因/规则层**——
  一切数字与判定只来自 `report.json`；报告层出现第二份比率计算会被口径唯一性守门判红。
- **无外链硬断言常驻在渲染出口**：`markdown.render_markdown()` / `html.render_html()` 每次返回前都调
  `assert_no_external_resources()`——不是"测试里验一次"，而是"含外链当场炸"。
- **证据完整性硬门**：每条建议缺任一项证据（口径 / 阈值 / 分子分母 / 样本量）→ 该条**不输出**（视为内部错误）。

退出码：命中"建议移除" → `1`（检出问题，不是跑挂）；无"建议移除" → `0`。

### 解析层（M2）已支持的范围

| 数据源 | 布局 | 版本检测键 |
|---|---|---|
| Claude Code 会话日志 | `~/.claude/projects/*/*.jsonl` | 行顶层 `version` |
| Codex rollout | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | `session_meta.payload.cli_version` |
| Claude Code 配置 | `~/.claude.json`、`~/.claude/settings.json`、插件清单 | —（配置侧事实，非事件流） |

日志**按首行形态判别**归属解析器（不靠目录名），故真实布局与 `data/synthetic/logs/` 走同一条通路。
检测键取值不在**显式支持集**内 → 退出码 4 并打印"未识别版本 + 期望集合 + 检测键路径"，
**绝不静默按最宽松规则解析**。

## 退出码

| 码 | 语义 |
|---|---|
| 0 | 成功 |
| 1 | 运行完成但**检出问题**（如命中"建议移除"、基准未达标）——不是跑挂 |
| 2 | 用法错误 / 未知名 / 参数非法 / **本构建尚未包含的命令** |
| 4 | 数据不可用（数据源目录不存在或为空 / schema 版本不识别） |

> 退出码 `3`（阶段未就绪）是骨架期的占位语义，已随 M2 解析层落地**整项退役**；
> 测试用 `not hasattr` 断言防其复活。

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

## 合成数据（基准输入，随包入仓）

`data/synthetic/` 是**程序化生成**的合成日志与植入真值，用于真值基准对账（不依赖任何真实用户日志）：

```bash
# 重新生成（确定性：自研 splitmix64 + 固定 seed，无时钟、无 stdlib random）
python tools/gen_synthetic_logs.py --out data/synthetic

# 只校验冻结产物位级一致（CI 与本地守门都用它）
python tools/gen_synthetic_logs.py --check
```

- `data/synthetic/logs/claude_alpha.jsonl` / `codex_alpha.jsonl`：Claude 形态与 Codex 形态的合成会话日志。
- `data/synthetic/truth.json`：**只存输入与期望**（哪个 server 的失败率是多少、各失败模式多少条）；
  观测值一律由基准运行时实算——真值库出现 `observed_*` 字段会被守门测试判红。
- `data/synthetic/manifest.json`：覆盖度声明（server 失败率形态 / 失败模式 / 三态 / 阈值边界 / 反向样例逐项"总数-采样数"双登记）。

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

## 已知环境问题

- **wheel（非 editable）安装下默认规则目录解析不到**：规则包 `data/rules/*.json` **不在 wheel 内**
  （`pyproject.toml` 未声明 `package-data`），`config.default_rules_dir()` 的"包外三级"定位只对
  源码态 / `pip install -e` 成立。故 wheel 安装后必须显式传 `--rules-dir <仓库>/data/rules`，
  否则以退出码 4 报 `规则目录不存在`（**已实测，不是推测**）。首期发布物是**源码包 + editable 安装**
  （README 快速开始那条命令），不受影响。M6 实测留档见 `plan/verify/README.md` §三。

## 许可

MIT
