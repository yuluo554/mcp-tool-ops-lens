# HANDOFF-M3 · 交接（下一棒：M3 聚合归因 —— sqlite3 聚合 + 五分类规则匹配）

> 用法：新对话 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务`
> 上一棒：M2 解析层（✅ 2026-10-16 完成）。本文件写于 M2 收尾，指向 M3。

---

## 一、当前进度与证据（已完成的，别重做）

### 1.1 M0 骨架（已实测，别重做）

- `plan/00–06` 六份齐备；`data/README.md` 含字段语义实测结论（§五）。
- 包骨架可装；退出码语义落 `exit_codes.py`；UTF-8 入口守卫在位；CI workflow 落盘（**未接远端**）。

### 1.2 M1 合成数据与规则包（**产物已作为 M2 输入实测通过**）

```
tools/gen_synthetic_logs.py          # splitmix64 + 固定 seed + --check
tools/mutation_check.py              # 变异验证（M1 10 项 + M2 6 项 = 16/16）
data/synthetic/logs/claude_alpha.jsonl   # 394 行（Claude 形态）
data/synthetic/logs/codex_alpha.jsonl    # 27 行（Codex 形态）
data/synthetic/truth.json            # 只存输入与期望
data/synthetic/manifest.json         # 覆盖度双登记
data/rules/{failure_patterns,thresholds,params}.json
```

### 1.3 M2 解析层（本棒完成，**产物可直接作为 M3 输入**）

```
src/opslens/parsers/__init__.py      # 包导出
src/opslens/parsers/common.py        # JSONL 迭代(带源行号) / 文本归一 / 错误文本截断
src/opslens/parsers/versions.py      # 显式支持版本集 + 检测键路径（版本检测唯一出处）
src/opslens/parsers/discovery.py     # 按首行形态判别解析器 + 目录前置检查
src/opslens/parsers/claude_jsonl.py  # Claude 会话日志 → IR（三态 + 轮次 token）
src/opslens/parsers/claude_config.py # 配置侧事实（白名单键，env 禁读）
src/opslens/parsers/codex_rollout.py # Codex rollout → IR（Exit code/Wall time/会话级 token）
src/opslens/pipeline.py              # 编排层（本棒只落地 scan 阶段）
tests/test_parsers.py                # 解析层守门（58 条）
```

**证据（M2 出口门实跑记录）**：
- 双解释器全量测试：`py -X utf8 -m pytest` → **163 passed**；`py -3.12 -X utf8 -m pytest` → **163 passed**。
- **解析结果与植入真值逐 server 对账一致**：合成目录 2 文件 / **202 次调用**（ok=122 / error=75 / unknown=5），
  6 个 Claude server + Codex 侧三态计数与 `truth.json` **逐项相等**。
- **端到端双跑 IR 逐字节一致**（两次 `scan --out` 的 sha256 相同）。
- **变异验证 16/16 通过**（含"版本集合改万能匹配 → 必红"、"缺失 is_error 洗成 ok → 必红"）。

### 1.4 scan 通路现状（M3 的输入接口）

```bash
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens scan --home data/synthetic --out events.json
# → exit 0；打印 "解析完成：2 个文件 / 202 次工具调用（ok=122 error=75 unknown=5）"
```

`events.json` 结构（`opslens.events/1`）：

```json
{
  "schema": "opslens.events/1",
  "count": 202,
  "home": "...",
  "sources": [{"relative": "...", "kind": "claude_jsonl"}],
  "schema_versions": {"claude_code": ["2.1.233"], "codex": ["0.146.0-alpha.3.1"]},
  "coverage_note": "...",
  "events": [
    {"source": "claude_code", "source_version": "2.1.233", "session_id": "...", "seq": 2,
     "timestamp": "...", "server": "fake-high-fail", "tool": "tool_exec", "call_id": "...",
     "status": "ok|error|unknown", "error_text": "...",
     "tokens": {"input": N, "output": N, "cache_read": N, "cache_creation": N},
     "duration_ms": null, "turn_tokens_attributed": true, "notes": []}
  ]
}
```

**事件已按 `(source, session_id, seq)` 排序**，M3 读入后可直接灌 sqlite，无需重排。

---

## 二、下一棒待办（M3 = `plan/05 §M3` 的 DoD 逐项）

按 `plan/05-里程碑.md` §M3 做，顺序建议：

1. **`src/opslens/aggregate.py`（sqlite3 内存库）**
   - 指标按 `plan/03 §2.1` 表**逐项**实现；SQL 列名与表一一对应。
   - **对账等式**：`calls_ok + calls_error + calls_unknown == calls_total`（锁进测试）。
   - `failure_rate` 分母**不含 unknown**；分母为 0 → `null` + `insufficient_data=true`。
   - token 四项**分列**；`token_samples` / `token_missing` 单列；均值名带 **`turn_` 前缀**。
   - 耗时：Claude 侧 `null` + `duration_available=false`（**不用 lastToolDuration 冒充**）。
   - 两级维度：server 级 `GROUP BY source, server`；tool 级 `GROUP BY source, server, tool`；
     **两级都要输出 unknown 计数**。
   - `retry_count`：窗口值取 `params.json` 的 `retry.window_seconds`（**不写死**）。
2. **`src/opslens/attribute.py`（规则匹配，非 AI 评分）**
   - 五分类 `timeout` / `permission_denied` / `invalid_args` / `content_refusal` / `other`。
   - **规则门控**：`status=="verified"` **且** `verified_samples` 非空才进计算路径（K10）；
     未生效规则落 `other` 且**报告列出原因**（用现成的 `rules.ineffective_patterns()`）。
   - **只在 `error_text` 上匹配**（`failure_patterns.json` 的 note 已写明：宽模式会在成功记录上误命中）。
3. **`pipeline.py` 接上 aggregate / attribute 两阶段**；CLI 把 `aggregate` / `attribute` 从
   "本构建尚未包含"移入 `IMPLEMENTED_COMMANDS`。
4. **口径唯一性守门**：AST 断言 `BinOp(Div)` **只出现在 `aggregate.py` / `attribute.py` / `tests/`**。
5. **变异验证**：新增 M3 项（至少含"`BinOp(Div)` 挪进报告层 → 必红"、"unknown 计入失败率分母 → 必红"、
   "未生效规则进计算路径 → 必红"）。
6. **收尾**：DoD 验证 → 回写 `plan/00` / `plan/05` / `plan/06` → 写 **`plan/HANDOFF-M4.md`** → commit。

---

## 三、既定口径清单（K 编号，**动了会打挂测试/基准**）

| K | 口径 | 落点 | 动了会打挂什么 |
|---|---|---|---|
| **K1** | **成败三态**：只认 `is_error is True` 为 error；`False` 为 ok；**缺失 = unknown，不进失败率分母** | `data/README §五A/E`、`parsers/claude_jsonl.py` | 模块 2/3/4 全部计数与基准真值 |
| **K2** | **token = 调用轮次归属**，四项（input/output/cache_read/cache_creation）**分列不合并** | `data/README §五B` | token 聚合、报告字段 |
| **K3** | **Codex token 不摊到单次工具调用**（会话级单列） | `data/README §五D` | Codex 侧任何 per-tool token 结论 |
| **K4** | **Claude 侧按工具耗时不可得**，`duration_ms=None`；**不得用 `lastToolDuration` 冒充** | `data/README §五B`（**M2 已复核补充**，见下） | 耗时均值、报告样本量说明 |
| **K5** | **`settings.json` 的 `env` 是禁读键**；白名单只读 `permissions.allow` / `enabledPlugins` | `plan/02 §五`、`parsers/claude_config.py` | `tests/test_privacy.py`、`tests/test_parsers.py` |
| **K6** | **退出码语义**：0 成功 / 1 检出问题 / 2 用法 / ~~3 阶段未就绪~~（**M2 已退役**）/ 4 数据不可用 | `exit_codes.py`、`plan/02 §六` | `test_cli.py`、`test_exit_codes.py`、README 退出码表 |
| **K7** | **确定性写盘契约**：`sort_keys=True` + `ensure_ascii=False` + LF + 结尾换行 + 原子写，**唯一入口 `serialize.py`** | `src/opslens/serialize.py` | `test_serialize.py`、所有产物双跑一致 |
| **K8** | **零第三方依赖 / 零出网 / 无时钟无随机**（stdlib 冻结名单在 `tests/test_discipline.py`） | `plan/02 §一/§五` | `test_discipline.py`（新增 stdlib 要同步进冻结名单） |
| **K9** | **阈值/口径参数全在 `data/rules/*.json`**，代码零数值字面量（含 docstring/注释） | `plan/03 §4.1` | 零字面量门禁 |
| **K10** | **规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空 | `config.py`、`plan/03 §3.2` | `tests/test_rules_gate.py` |
| **K11** | **IR 排序键 = `(source, session_id, seq)`**，`seq` 是源行号，全程不读时钟 | `schema.py`、`parsers/` | 双跑逐字节一致 |
| **K12** | **真值库只存输入与期望**，观测由基准运行时实算（出现 `observed` 即红） | `plan/04 §3.2` | 模块 5 基准有效性 |
| **K13** | **合成覆盖度 ≠ 已核对样例**：`synthetic_coverage` 只登记演练关系，**不得**写进 `verified_samples` | `data/rules/failure_patterns.json` | `test_rules_gate.py`、`test_synthetic_data.py` |
| **K14**（M2 新增） | **schema 版本 = 显式集合**，不是正则放宽匹配；不在集内 → exit 4 + 打印检测键路径 | `parsers/versions.py` | `test_parsers.py` 版本断言、变异项 11/12 |

### K4 的 M2 复核补充（**重要，别踩**）

M2 用只读探针对 **94 个 jsonl 全量**复核了 M1 遗留的疑点：真实日志里 `toolUseResult.durationMs`
**确实存在**（**159 条**，均为 `int` 毫秒），但：

- 只覆盖 `Glob`（112/121，92.6%）与 `WebFetch`（47/48，97.9%）两个**内置**工具；
- `Bash`（711）/`Read`（512）/`PowerShell`（328）/`Edit`（252）/`Grep`（181）/`Write`（116）以及
  **全部 `mcp__*` 工具覆盖率为 0**；
- 该字段语义（是否含排队/UI 等待）**未经核对**。

**结论：K4 不变**——Claude 侧 `duration_ms` 恒为 `None`。两条理由都可指认：① 对本项目主体（MCP 工具）覆盖率为 0；
② 未核对字段不进计算路径（与 `is_error` 三态同源纪律）。已登记进 `data/README.md §五 B`，
并有守门 `test_claude_duration_is_unavailable_not_zero` 断言**解析器源码里不出现 `durationMs`**。

---

## 四、本机环境坑（只写实测过的，M2 新增两条）

1. **双 Python 通道可用**：`py -0p` → **3.8.8** 与 **3.12**。一律 `py -X utf8` 跑命令；
   **3.9+ 语法在 3.8 直接 SyntaxError**（禁 `match`、禁 `X | Y` 类型标注、禁 `dict | dict`）。
2. **`ast.Index` 包装（3.8 特有）**：3.8 上 `node.slice` 是 `ast.Index(value=Constant)`，
   3.9+ 才是裸 `Constant`——正解见 `tests/test_privacy.py::_string_key`。
3. **Git Bash `/tmp` 与 Windows Python 路径不通**：临时文件一律用**工作区相对路径**。
4. **变异脚本要"先断言变异生效"**：替换前 assert marker 存在，替换后 assert 文件已变，还原后再 assert 字节一致。
5. **变异的 marker 别撞 docstring**，要足够长以唯一定位代码行。
6. **venv 通道**：`py -3.12 -m venv .venv --without-pip` → `ensurepip` → `pip install setuptools wheel`
   → 才能 `pip install -e ".[dev]"`。镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple` + `NO_PROXY="*" no_proxy="*"`。
7. **扫描面非空要自证**：文本/文件扫描类守门必须断言"扫到的文件数 ≥ N"，否则目录写错 → 扫 0 个 → 永远绿。
8. **写扫描类守门时，自己的测试/脚本也在扫描面内**：**正解：运行时拼接构造**（如 `"windows" + "-" + "mcp"`）。
9. **"只查冻结产物"的守门会漏掉生成器变异**：**正解：冻结产物 + 重生成结果两层都断言**。
10. **产物确定性可用 sha256 跨进程复核**。
11. **【M2 新增】禁读键的守门要防"假变异"**：M2 变异项首版把 `picked = _pick(raw, 白名单)` 改成 `dict(raw)`，
    跑出 **exit=0（变异未生效）**——因为输出结构是按显式键**重建**的，整体透传并不泄漏 `env`。
    **正解：按真实故障形态变异**（往输出结构里加 `"env": raw.get("env")`）。
    教训：变异"没红"有两种可能——守门是假门，**或者变异本身是假的**；先判断是哪种，别急着改测试。
12. **【M2 新增】真实 server 名禁止词表会命中**文件名**：Claude 的插件清单文件名
    （`installed` + `_plugins.json`，此处**故意拆写**，见下）与禁止词表里的一个真实 server 名同形。
    **正解：运行时拼接构造**（`"installed" + "_plugins"`），
    **不是**把该词从禁止词表里删掉——放宽守门来迁就自己的代码是本末倒置。
    ⚠️ **本文件自身也在扫描面内**：M2 收尾时本文件的初版把该词写成字面量，被自家守门判红过一次
    （与 HANDOFF-M1 §四 第 8 条同一个坑，换个文件又踩了一遍）。
13. **【M2 新增】文件形态判别优于路径判别**：`discovery.py` 按**首行形态**（有无 `payload` / `message`）
    判别解析器，使真实布局（`projects/` 与 `sessions/`）与合成目录（`logs/`）走同一条通路。
    若改成"按目录名判别"，测试夹具就得伪造目录树，且真实用户的非标准布局会被静默漏掉。

---

## 五、DoD 逐项 Checklist（M2 出口门，逐项已验）

- [x] 三解析器产 `ToolCallEvent` 流（`claude_jsonl` / `claude_config` / `codex_rollout`）
- [x] **成败三态**：`is_error is True` → error、`False` → ok、**缺失 → unknown**
- [x] schema 版本检测：不在显式支持集 → exit 4 + 打印检测键路径；**变异验证必红**
- [x] `env` 禁读守门：源码无 `env` 取值路径（既有守门）+ 假凭据 fixture 断言产物不含该值
- [x] 解析层纯函数：AST 断言不 import 规则层/时钟/随机，且不写盘（含探针自证）
- [x] **双跑 IR 逐字节一致**：单元级 + 端到端（CLI 产物 sha256）双锁
- [x] 退出码 `3` 整项退役（四处同步：常量 / CLI+测试含 `not hasattr` / 文档 / 决策记录）
- [x] `tests/` 全绿：**双解释器各 163 passed**
- [x] 变异验证 **16/16**（含发现并修正 1 个**假变异**，见 §四 第 11 条）
- [x] **HANDOFF-M3 落盘并 commit**（本文件）
- [ ] M3 聚合 + 归因 —— **下一棒（见 §二）**

**偏差说明（如实留档）**：
- **CI 未实跑**：本棒无远端。CI 里新增的 `scan` 冒烟与"未知版本 → exit 4"步骤只做过**本地等价校验**
  （已在 Git Bash 手动跑通同样命令），待 M6 首推验证。
- **支持版本集只覆盖本机实测值**：Claude 7 个（2.1.216/220/223/226/233/238/263）、Codex 1 个。
  这是**显式集合**的必然代价：新版本需手写进 `versions.py`。换来的是"未知版本一定报错而非静默错解"。
- **`claude_config.py` 产出的是配置侧事实、不是事件流**（`plan/03 §1.1` 已如此规定）；
  它尚未参与聚合，M3 起可用于"已安装 server 清单 vs 实际被调用 server"的对照。
- **`unknown` 样本量偏少**（合成数据仅 5 条）：足以演练通路与对账，但**不足以**做 unknown 比例的统计推断。

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -X utf8 -m pytest -q

# 变异验证（M1 10 项 + M2 6 项）
py -X utf8 tools/mutation_check.py

# 合成数据：重生成 / 位级校验
py -X utf8 tools/gen_synthetic_logs.py --out data/synthetic
py -X utf8 tools/gen_synthetic_logs.py --check

# CLI 冒烟（源码态：先设 PYTHONPATH）
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens --help
py -X utf8 -m opslens scan --home data/synthetic --out events.json   # → exit 0
py -X utf8 -m opslens scan --home . --rules-dir ./nope               # → exit 4（规则包缺失）
py -X utf8 -m opslens aggregate --events events.json                 # → exit 2（本构建尚未包含）

# 解析结果 vs 真值 快速对账（M3 可复用这段核对口径）
py -X utf8 -c "
import collections, json
from opslens import pipeline
ev, _ = pipeline.scan_home('data/synthetic')
c = collections.defaultdict(collections.Counter)
for e in ev:
    c[(e.source, e.server)][e.status] += 1
print(json.dumps({str(k): dict(v) for k, v in c.items()}, ensure_ascii=False, indent=2))
"
```

**扫描面清单**（新增文件时注意）：
- `tests/test_discipline.py::STDLIB_FROZEN` —— 新增 stdlib import 要同步进名单。
- `tests/test_discipline.py::SCAN_DIRS` = `src/` + `tools/`（解析层也在内）。
- `tests/test_privacy.py::REAL_SERVER_NAMES` / `REAL_SERVER_NAME_TOKENS` —— 真实 server 名禁止词表。
- `tests/test_privacy.py::ALLOWED_MENTION_FILES` —— 允许提及键名的台账文件白名单。
- `tests/test_encoding.py::_printable_entry_points` —— `tools/` 全部入口脚本的编码守门扫描面。
- `tests/test_readme_gate.py` —— README 命令/旗标/extras 与 CLI/pyproject 对账。
- `tests/test_parsers.py::FORBIDDEN_PARSER_IMPORTS` —— 解析层禁止 import 的模块清单。
- `tests/test_synthetic_data.py` —— 合成数据与生成器守门。

---

## 七、下一棒启动提示词

```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M3.md" 继续完成任务
```
