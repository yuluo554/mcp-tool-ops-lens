# HANDOFF-M4 · 交接（下一棒：M4 真值基准 —— 引擎输出 vs 植入真值对账）

> 用法：新对话 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务`
> 上一棒：M3 聚合归因（✅ 2026-10-16 完成）。本文件写于 M3 收尾，指向 M4。

---

## 一、当前进度与证据（已完成的，别重做）

### 1.1 M0–M2（已实测，别重做）

- `plan/00–06` 六份齐备；`data/README.md` 含字段语义实测结论（§五）。
- 包骨架可装；退出码语义落 `exit_codes.py`（**`3` 已退役**）；UTF-8 入口守卫在位；CI workflow 落盘（**未接远端**）。
- M1：`tools/gen_synthetic_logs.py`（splitmix64 + 固定 seed + `--check`）、`data/synthetic/{logs,truth.json,manifest.json}`、`data/rules/*.json`。
- M2：`src/opslens/parsers/`（三解析器 + 版本检测 + 发现逻辑）、`pipeline.py`（scan 阶段）、`tests/test_parsers.py`。

### 1.2 M3 聚合归因（本棒完成，**产物可直接作为 M4 输入**）

```
src/opslens/aggregate.py    # sqlite3 内存库两级聚合（plan/03 §2.1 指标逐项）
src/opslens/attribute.py    # 五分类规则匹配（K10 门控）
src/opslens/pipeline.py     # 编排层（scan → aggregate → attribute 三阶段）
tests/test_aggregate.py     # 聚合守门（29 条）
tests/test_attribute.py     # 归因守门（18 条）
```

**证据（M3 出口门实跑记录）**：
- 双解释器全量测试：`py -X utf8 -m pytest` → **211 passed**；`py -3.12 -X utf8 -m pytest` → **211 passed**。
- **两级聚合与植入真值逐 server 对账一致**：7 个 server 维度的
  `calls_total/ok/error/unknown`、`failure_rate`、`retry_count` 与 `truth.json` **逐项相等**。
- **失败模式归因与真值逐 server 对账一致**：`timeout` / `permission_denied` / `invalid_args` / `other`
  四类分布与 `truth.json` 的 `failure_modes` **逐项相等**；未生效规则 `F-REFUSE-1` 覆盖的内容拒绝样例落 `other`。
- **端到端双跑逐字节一致**：两次 `aggregate --out` / 两次 `attribute --out` 的产物 sha256 分别相同。
- **变异验证 24/24 通过**（M1 十项 + M2 六项 + M3 八项）。

### 1.3 三阶段通路现状（M4 的输入接口）

```bash
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens scan      --home data/synthetic --out events.json   # → exit 0
py -X utf8 -m opslens aggregate --events events.json --out agg.json       # → exit 0
py -X utf8 -m opslens attribute --events events.json --out attr.json      # → exit 0
```

`agg.json` 结构（`opslens.aggregate/1`）：

```json
{
  "schema": "opslens.aggregate/1",
  "rate_precision": 6,
  "retry_window_seconds": 120,
  "server_level": [{"level":"server","source":"claude_code","server":"fake-high-fail",
    "calls_total":40,"calls_ok":16,"calls_error":24,"calls_unknown":0,
    "failure_rate":0.6,"failure_rate_numerator":24,"failure_rate_denominator":40,
    "insufficient_data":false,"retry_count":0,
    "tokens_input":N,"tokens_output":N,"tokens_cache_read":N,"tokens_cache_creation":N,
    "token_samples":40,"token_missing":0,"turn_token_avg":N,
    "duration_avg_ms":null,"duration_samples":0,"duration_missing":40,
    "duration_available":false}],
  "tool_level": [{"level":"tool","tool":"tool_exec", ...}],
  "totals": {"calls_total":202,"calls_ok":122,"calls_error":75,"calls_unknown":5, ...},
  "coverage_note": "..."
}
```

`attr.json` 结构（`opslens.attribute/1`）：

```json
{
  "schema": "opslens.attribute/1",
  "categories": ["timeout","permission_denied","invalid_args","content_refusal","other"],
  "effective_rule_ids": ["F-TIMEOUT-1","F-PERM-1","F-ARGS-1"],
  "ineffective_rules": [{"id":"F-REFUSE-1","reasons":["status=pending","verified_samples 为空"]}],
  "totals": {"calls_error":75,"matched":71,"other":4,"unmatched_note":"..."},
  "by_category": [{"category":"timeout","calls":24}, ...],
  "by_server": [{"source":"claude_code","server":"fake-high-fail","calls_error":24,"categories":{...}}],
  "matched_patterns": [{"rule_id":"F-TIMEOUT-1","pattern":"...","calls":N}],
  "coverage_note": "..."
}
```

---

## 二、下一棒待办（M4 = `plan/05 §M4` 的 DoD 逐项）

按 `plan/05-里程碑.md` §M4 做，顺序建议：

1. **`src/opslens/bench.py`（或 `bench/` 包）**
   - 对账：**引擎输出 vs 植入真值**（`data/synthetic/truth.json`），**全维度**一致；
     差异**逐条列出**（不能只报"不一致"）。
   - 维度至少覆盖：三态计数 / `failure_rate` / `retry_count` / 失败模式分布 / 两级维度。
   - **真值只存输入与期望（K12）**：观测一律由基准**运行时实算**，绝不读 `truth.json` 里的"观测"字段
     （该库已被守门禁止出现 `observed_*`）。
2. **分层：样本驱动 + 规则驱动两层**
   - 样本驱动层：直接对合成日志的三态/失败率对账（M2/M3 已做单元级对账，M4 要**成体系**）。
   - 规则驱动层：对规则包的生效门控与失败分类对账（未生效规则落 `other` 的期望）。
   - 新增基准**注册进 `--only` 白名单**；`opslens bench --only NOPE` → **exit 2**。
3. **每套件配可证伪探活**：注入缺陷（如把 `is_error=True` 判成 `ok`）→ **必报未达标（exit 1）**。
   - 这是 M4 最容易做成假门的地方：**必须让探活真的跑一次注入并断言变红**（参考 `tools/mutation_check.py` 的手法）。
4. **退出码三语义（0/1/2）锁进测试**
   - `0` 达标 / `1` 未达标（检出差异）/ `2` 用法与未知名。
   - **空分母分支**：`not_enabled=true` + notes + **exit 1**（"未启用"不得冒充通过）。
5. **覆盖声明"总数/采样数双登记" + 显式"抽样覆盖非穷举"**（`manifest.json` 已有素材，基准要消费它）。
6. **每次里程碑收尾复跑双基线**（解析 F1 + e2e）：把 M2/M3 的对账固化成基准套件，收尾时复跑。
7. **收尾**：DoD 验证 → 回写 `plan/00` / `plan/05` / `plan/06` → 写 **`plan/HANDOFF-M5.md`** → commit。

---

## 三、既定口径清单（K 编号，**动了会打挂测试/基准**）

| K | 口径 | 落点 | 动了会打挂什么 |
|---|---|---|---|
| **K1** | **成败三态**：只认 `is_error is True` 为 error；`False` 为 ok；**缺失 = unknown，不进失败率分母** | `data/README §五A/E`、`parsers/claude_jsonl.py`、`aggregate.py` | 模块 2/3/4 全部计数与基准真值 |
| **K2** | **token = 调用轮次归属**，四项（input/output/cache_read/cache_creation）**分列不合并** | `data/README §五B` | token 聚合、报告字段 |
| **K3** | **Codex token 不摊到单次工具调用**（会话级单列） | `data/README §五D` | Codex 侧任何 per-tool token 结论 |
| **K4** | **Claude 侧按工具耗时不可得**，`duration_ms=None` + `duration_available=false`；**不得用 `lastToolDuration` 冒充** | `data/README §五B` | 耗时均值、报告样本量说明 |
| **K5** | **`settings.json` 的 `env` 是禁读键**；白名单只读 `permissions.allow` / `enabledPlugins` | `plan/02 §五`、`parsers/claude_config.py` | `tests/test_privacy.py`、`tests/test_parsers.py` |
| **K6** | **退出码语义**：0 成功 / 1 检出问题 / 2 用法 / 4 数据不可用（**3 已于 M2 退役**） | `exit_codes.py`、`plan/02 §六` | `test_cli.py`、`test_exit_codes.py`、README 退出码表 |
| **K7** | **确定性写盘契约**：`sort_keys=True` + `ensure_ascii=False` + LF + 结尾换行 + 原子写，**唯一入口 `serialize.py`** | `src/opslens/serialize.py` | `test_serialize.py`、所有产物双跑一致 |
| **K8** | **零第三方依赖 / 零出网 / 无时钟无随机**（stdlib 冻结名单在 `tests/test_discipline.py`） | `plan/02 §一/§五` | `test_discipline.py`（新增 stdlib 要同步进冻结名单） |
| **K9** | **阈值/口径参数全在 `data/rules/*.json`**，代码零数值字面量（含 docstring/注释） | `plan/03 §4.1` | 零字面量门禁 |
| **K10** | **规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空 | `config.py`、`plan/03 §3.2` | `tests/test_rules_gate.py`、`test_attribute.py` |
| **K11** | **IR 排序键 = `(source, session_id, seq)`**，`seq` 是源行号，全程不读时钟 | `schema.py`、`parsers/` | 双跑逐字节一致 |
| **K12** | **真值库只存输入与期望**，观测由基准运行时实算（出现 `observed` 即红） | `plan/04 §3.2` | 模块 5 基准有效性 |
| **K13** | **合成覆盖度 ≠ 已核对样例**：`synthetic_coverage` 只登记演练关系，**不得**写进 `verified_samples` | `data/rules/failure_patterns.json` | `test_rules_gate.py`、`test_synthetic_data.py` |
| **K14**（M2） | **schema 版本 = 显式集合**，不是正则放宽匹配；不在集内 → exit 4 + 打印检测键路径 | `parsers/versions.py` | `test_parsers.py` 版本断言、变异项 11/12 |
| **K15**（M3 新增） | **口径唯一性**：`BinOp(Div)` 只允许出现在 `aggregate.py` / `attribute.py` / `tools/gen_synthetic_logs.py`（真值生成器须与引擎独立，否则真值 = 引擎自证） | `tests/test_aggregate.py::DIV_ALLOWED_FILES` | 口径唯一性守门、变异项 19 |
| **K16**（M3 新增） | **`error_text` = 空白归一**（多行折叠为单行）+ 上限截断；**不是**只取首行 | `parsers/common.py::truncate_error_text` | `test_parsers.py`、`test_attribute.py`、变异项 23 |
| **K17**（M3 新增） | **归因只在 `error_text` 上匹配**，且**只消费 `status=="error"`** 的事件（成功与 unknown 都不参与） | `attribute.py` | `test_attribute.py`、变异项 22 |
| **K18**（M3 新增） | **重试期望必须可由日志复算**：合成数据按 server 形态分节奏（重试型在窗口内、其余在窗口外） | `tools/gen_synthetic_logs.py::_validate_retry_separation` | `test_aggregate.py` 重试对账、变异项 24 |

### K15/K16 的 M3 补充（**重要，别踩**）

1. **`BinOp(Div)` 白名单是三处不是两处**：`plan/03 §2.3` 原文只写 `aggregate.py` / `attribute.py` / `tests/`。
   实现时发现 `tools/gen_synthetic_logs.py` 必须推导**期望值**（`_round_rate` / `expected_failure_rate`），
   而它与引擎**必须相互独立**（共用实现 = 真值沦为"引擎自证"，K12 明禁）。
   这是**扩充而非放宽**：白名单每处都单独论证过，新增落点必须改测试才生效。
2. **`error_text` 归一形态**：实测两侧日志的失败签名都在**第二行及之后**
   （Claude `Command timed out after` 在 `Exit code 143` 后；Codex `Exit code: 124` 在 `Script failed` 后）。
   只留首行 → 规则表这两条模式**永远无法命中**，归因必然与真值不符（探针实测 timeout 全落 `other`）。
   **M4 若要做"归因维度对账"，务必先确认归一形态没被改回去。**

---

## 四、本机环境坑（只写实测过的，M3 新增三条）

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
11. **禁读键的守门要防"假变异"**：变异"没红"有两种可能——守门是假门，**或者变异本身是假的**；先判断是哪种。
12. **真实 server 名禁止词表会命中**文件名**（`installed` + `_plugins.json` 与一个真实 server 名同形）。
    **正解：运行时拼接构造**，**不是**把该词从禁止词表里删掉（放宽守门来迁就自己的代码是本末倒置）。
    ⚠️ **扫描面是全仓**：`test_real_server_names_absent_from_repo_content` 从仓库根 `os.walk`，
    故 **`plan/` 下的文件（含本交接文件）也在扫描面内**——写文档时若把某个真实 server 名写成字面量，
    会被自家守门判红（HANDOFF-M1 §四 第 8 条同源；M2/M3 各踩过一次）。豁免名单见
    `tests/test_privacy.py::ALLOWED_MENTION_FILES`（只有需要说明实测结论的台账文件 + 该测试自身）。
    **本文件即在该扫描面内**——M3 收尾时已实测通过。
13. **文件形态判别优于路径判别**：`discovery.py` 按**首行形态**判别解析器，真实布局与合成目录走同一条通路。
14. **【M3 新增】`sqlite3` 窗口函数（`LAG` / `WINDOW`）本机双解释器都可用**：
    3.8.8 带 sqlite 3.34.0，3.12 带 3.49.1，`LAG(...) OVER (...)` 均可用（已实测）。
    `WINDOW w AS (...)` 子句在 3.34 上可用；若将来要兼容更老的 sqlite，需回退到相关子查询写法。
15. **【M3 新增】"探针先行"能抓出真缺陷，别只写测试**：本棒的两个真实缺陷
    （错误文本首行截断丢签名、重试期望不可推导）都是**先用一次性只读探针实测**才发现的，
    写测试时若只照 plan 文档的措辞做，两个缺陷都会**静默通过**（因为测试与实现同错）。
    探针脚本用完即删（`tools/` 下会被编码守门扫到，`tests/test_encoding.py` 要求每个入口脚本都调 `ensure_utf8_stdio`）。
16. **【M3 新增】"期望值"与"实现"必须相互独立**：真值的期望值若与引擎共用一份计算实现，
    就变成"引擎自证"（K12 明禁"冻结观测"的同族错误）。M3 让生成器**独立实现**窗口规则复算，
    并以"变异生成器 → 对账必红"（变异项 24）验证两条通路确实独立。

---

## 五、DoD 逐项 Checklist（M3 出口门，逐项已验）

- [x] `aggregate.py`（sqlite3）：指标按 `plan/03 §2.1` 表逐项实现
- [x] **对账等式**：`calls_ok + calls_error + calls_unknown == calls_total`（锁进测试）
- [x] `failure_rate` 分母**不含 unknown**；分母为 0 → `null` + `insufficient_data`
- [x] token 四项分列；`token_samples` / `token_missing` 单列；名称带 `turn_` 前缀
- [x] 耗时：Claude 侧 `null` + `duration_available=false`（**不用 lastToolDuration 冒充**）
- [x] `attribute.py`：五分类规则匹配；**未生效规则落 `other` 且报告列出原因**
- [x] **口径唯一性守门**：`BinOp(Div)` 只出现在白名单三处（含真值生成器，逐条论证）
- [x] 两级维度都输出 `unknown` 计数
- [x] **聚合与归因逐 server 与植入真值对账一致**（全维度）
- [x] **端到端双跑逐字节一致**（`aggregate` / `attribute` 产物 sha256）
- [x] `tests/` 全绿：**双解释器各 211 passed**
- [x] 变异验证 **24/24**（M1 十项 + M2 六项 + M3 八项）
- [x] **HANDOFF-M4 落盘并 commit**（本文件）
- [ ] M4 真值基准 —— **下一棒（见 §二）**

**偏差说明（如实留档）**：
- **CI 未实跑**：本棒无远端。待 M6 首推验证。
- **本棒修正了 M2/M1 的两个真实缺陷**（均由探针实测发现）：错误文本首行截断丢失败签名；
  重试期望不可由日志推导（真值沦为植入断言）。修正后 `truth.json` / `manifest.json` **内容不变**
  （修正的是"期望值的可推导性"，不是期望值本身），`claude_alpha.jsonl` 仅时间戳变化。
- **口径唯一性白名单扩为三处**（含真值生成器）：对 `plan/03 §2.3` 措辞的扩充而非放宽，逐条论证见 §三 K15。
- **`unknown` 样本量偏少**（合成数据仅 5 条）：足以演练分母口径与对账，**不足以**做 unknown 比例的统计推断。
- **`report` / `bench` 仍未落地**：调用时按用法码 2 退出并明确报"本构建尚未包含"。
- **`claude_config.py` 产出的是配置侧事实、不是事件流**；M3 尚未把它用于
  "已安装 server 清单 vs 实际被调用 server"的对照——该对照属 M5 报告层素材（或 M4 基准的一个套件）。

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -X utf8 -m pytest -q

# 变异验证（M1 10 项 + M2 6 项 + M3 8 项）
py -X utf8 tools/mutation_check.py

# 合成数据：重生成 / 位级校验
py -X utf8 tools/gen_synthetic_logs.py --out data/synthetic
py -X utf8 tools/gen_synthetic_logs.py --check

# CLI 冒烟（源码态：先设 PYTHONPATH）
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens --help
py -X utf8 -m opslens scan      --home data/synthetic --out events.json   # → exit 0
py -X utf8 -m opslens aggregate --events events.json --out agg.json       # → exit 0
py -X utf8 -m opslens attribute --events events.json --out attr.json      # → exit 0
py -X utf8 -m opslens bench                                                # → exit 2（本构建尚未包含）
py -X utf8 -m opslens scan --home . --rules-dir ./nope                     # → exit 4（规则包缺失）

# 对账速查（M4 可复用这段核对口径）
py -X utf8 -c "
import json
from opslens import pipeline, aggregate, attribute, config
rules = config.load_rules()
events, _ = pipeline.scan_home('data/synthetic')
agg = aggregate.aggregate(events, rules)
attr = attribute.attribute(events, rules)
truth = json.load(open('data/synthetic/truth.json', encoding='utf-8'))
by = {(r['source'], r['server']): r for r in agg['server_level']}
for s in truth['claude']['servers']:
    r = by[('claude_code', s['server'])]
    print(s['server'], r['failure_rate'] == s['expected_failure_rate'], r['retry_count'] == s['expected_retry_count'])
print(attr['by_category'])
"
```

**扫描面清单**（新增文件时注意）：
- `tests/test_discipline.py::STDLIB_FROZEN` —— 新增 stdlib import 要同步进名单。
- `tests/test_discipline.py::SCAN_DIRS` = `src/` + `tools/`。
- `tests/test_aggregate.py::DIV_ALLOWED_FILES` —— `BinOp(Div)` 白名单（新增落点须改测试）。
- `tests/test_privacy.py::REAL_SERVER_NAMES` / `REAL_SERVER_NAME_TOKENS` —— 真实 server 名禁止词表。
- `tests/test_privacy.py::ALLOWED_MENTION_FILES` —— 允许提及键名的台账文件白名单。
- `tests/test_encoding.py::_printable_entry_points` —— `tools/` 全部入口脚本的编码守门扫描面。
- `tests/test_readme_gate.py` —— README 命令/旗标/extras 与 CLI/pyproject 对账。
- `tests/test_parsers.py::FORBIDDEN_PARSER_IMPORTS` —— 解析层禁止 import 的模块清单。
- `tests/test_synthetic_data.py` —— 合成数据与生成器守门。

---

## 七、下一棒启动提示词

```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M4.md" 继续完成任务
```
