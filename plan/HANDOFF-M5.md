# HANDOFF-M5 · 交接（下一棒：M5 交付 —— `opslens report` MD + HTML 示例报告）

> 用法：新对话 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务`
> 上一棒：M4 真值基准（✅ 2026-10-16 完成）。本文件写于 M4 收尾，指向 M5。

---

## 一、当前进度与证据（已完成的，别重做）

### 1.1 M0–M3（已实测，别重做）

- `plan/00–06` 六份齐备；`data/README.md` 含字段语义实测结论（§五）。
- 包骨架可装；退出码语义落 `exit_codes.py`（**`3` 已退役**）；UTF-8 入口守卫在位；CI workflow 落盘（**未接远端**）。
- M1：`tools/gen_synthetic_logs.py`（splitmix64 + 固定 seed + `--check`）、`data/synthetic/{logs,truth.json,manifest.json}`、`data/rules/*.json`。
- M2：`src/opslens/parsers/`（三解析器 + 版本检测 + 发现逻辑）、`pipeline.py`（scan 阶段）。
- M3：`src/opslens/aggregate.py`（sqlite3 两级聚合）、`src/opslens/attribute.py`（五分类规则匹配）、`pipeline.py`（三阶段编排）。

### 1.2 M4 真值基准（本棒完成，**产物可直接作为 M5 输入**）

```
src/opslens/bench.py        # 模块 5：四层套件对账 + 每套件可证伪探活 + 退出码 0/1/2
src/opslens/cli.py          # bench 子命令接通（IMPLEMENTED_COMMANDS 含 "bench"）
tests/test_bench.py         # 基准守门（40 条）
tools/mutation_check.py     # 变异验证 M4 六项（总 30 项）
.github/workflows/ci.yml    # bench 三条 CI 步骤（达标 / 未知名 exit 2 / 双基线复跑）
```

**证据（M4 出口门实跑记录）**：
- 双解释器全量测试：`py -X utf8 -m pytest` → **251 passed**；`py -3.12 -X utf8 -m pytest` → **251 passed**。
- `py -X utf8 -m opslens bench` → **12 个套件全部通过 / 差异 0 条 / 退出码 0**（四层：样本驱动 6 + 规则驱动 3 + 覆盖声明 1 + 双基线 2）。
- **解析对账基线 F1 = 1**：计数级混淆矩阵 `tp=78 / fp=0 / fn=0`，precision = recall = 1.0。
- **e2e 双跑逐字节一致**：`events` / `aggregate` / `attribute` 三产物在正序与倒序输入下 sha256 相同。
- **每套件探活全部变红**（12/12 逐个验证）；**基准报告双跑 sha256 相同**（`b902de50…`）。
- **退出码三语义实测**：`bench` → 0；`bench --only NOPE` → **2**；篡改真值/空规则包 → **1**（差异逐条列出 / `not_enabled` + notes）。
- **变异验证 30/30 通过**（M1 十项 + M2 六项 + M3 八项 + M4 六项）。

### 1.3 四阶段通路现状（M5 的输入接口）

```bash
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens scan      --home data/synthetic --out events.json   # → exit 0
py -X utf8 -m opslens aggregate --events events.json --out agg.json       # → exit 0
py -X utf8 -m opslens attribute --events events.json --out attr.json      # → exit 0
py -X utf8 -m opslens bench                                              # → exit 0（12 套件 / 0 差异）
py -X utf8 -m opslens bench --only NOPE                                   # → exit 2
py -X utf8 -m opslens bench --check                                       # → exit 0（只跑双基线）
```

`agg.json` 结构（`opslens.aggregate/1`）与 `attr.json` 结构（`opslens.attribute/1`）
见 HANDOFF-M4 §1.3（未变）。**M5 的报告层应消费这两份载荷，不得自己重算比率**（渲染层零判定）。

**bench 载荷**（`opslens.bench/1`，M5 可复用其"覆盖声明"节素材）：

```json
{
  "schema": "opslens.bench/1",
  "data_dir": "...", "home": "...",
  "selection": {"only": null, "check": false},
  "layers": ["baseline", "coverage", "rule", "sample"],
  "suites": [{"id": "S-THREE-STATE", "layer": "sample", "title": "...",
    "status": "pass", "not_enabled": false, "checks": 1,
    "diffs": [], "metrics": {...}, "notes": [],
    "probe": {"detected": true, "diffs": 3, "note": "..."}}],
  "totals": {"suites": 12, "passed": 12, "failed": 0, "not_enabled": 0, "diffs": 0, "probes_undetected": 0},
  "coverage_declaration": {"declaration": "抽样覆盖，非穷举：...",
    "dimensions": [{"dimension": "...", "required_forms": N, "sampled_forms": M, "items": K}],
    "totals": {...}, "note": "..."},
  "verdict": "pass",
  "coverage_note": "..."
}
```

---

## 二、下一棒待办（M5 = `plan/05 §M5` 的 DoD 逐项）

按 `plan/05-里程碑.md` §M5 做，顺序建议：

1. **`src/opslens/report/` 包**（`markdown.py` / `html.py`）+ `report.py`（或 `report/__init__.py`）
   - **单一渲染源 `report.json`**：MD/HTML 都由它渲染 → "两格式内容一致"是**结构性质**，不是人工比对。
   - **渲染层零判定**（AST 守门）：`report/` **无 `BinOp(Div)`**、**不 import 规则层/聚合层**——
     一切数字与判定**只来自 `report.json`**，渲染器只做排版。
   - **无外链硬断言**：渲染出口**常驻** `assert_no_external_resources`（不只测试里验一次）——
     HTML 内联 CSS、无 `<link>` / `<script src>` / `http(s)://` 外链，断网可开。
   - 产物：`report.json`（机读，`serialize.write_atomic()`）+ `report.md` + `report.html`。
2. **报告必含章节**（plan/03 §4.2）：
   ① 数据来源与覆盖声明（扫了哪些路径、哪些源、schema 版本）；② **`unknown`/样本缺失独立分区**（不混入统计）；
   ③ 建议清单（每条附**口径 + 阈值取值 + 分子/分母 + 样本量**）；④ 未生效规则清单（原因）；
   ⑤ 定位宣言 + "建议仅供参考，不自动修改配置"声明。
3. **建议层**（模块 4，`thresholds.json` 全可配，**零字面量门禁**）：
   `remove_candidate`（`failure_rate ≥ T_fail` 且 `calls_total ≥ N_min`）/ `investigate` /
   `cost_heavy`（`turn_token_avg ≥ T_tok` 且 `token_samples ≥ N_tok`）/ `low_signal`（**样本不足一律降级"数据不足"，不出建议**）。
   - 每条建议缺任一项证据 → **该条不输出**（视为内部错误）。
   - 触发口径应与 `tools/gen_synthetic_logs.py::expected_suggestion` 的期望值**对账**（真值已声明 `expected_suggestion`，**M5 可直接消费**）。
4. **`examples/report.md` / `report.html` 入仓**（基于合成数据）。
5. **README ↔ CLI 对账守门**（`build_parser()` 反射，`tests/test_readme_gate.py` 已存在）：README 增补 `report` 用法后须同步；
   README 安装行 extras 与 CI 一致。
6. **编码守门覆盖所有可打印入口**（主 CLI + `tools/` 全部脚本，`tests/test_encoding.py` 已存在）。
7. **收尾**：DoD 验证 → 回写 `plan/00` / `plan/05` / `plan/06` → 写 **`plan/HANDOFF-M6.md`** → commit。

---

## 三、既定口径清单（K 编号，**动了会打挂测试/基准**）

| K | 口径 | 落点 | 动了会打挂什么 |
|---|---|---|---|
| **K1** | **成败三态**：只认 `is_error is True` 为 error；`False` 为 ok；**缺失 = unknown，不进失败率分母** | `data/README §五A/E`、`parsers/claude_jsonl.py`、`aggregate.py` | 模块 2/3/4/5 全部计数与基准真值 |
| **K2** | **token = 调用轮次归属**，四项（input/output/cache_read/cache_creation）**分列不合并** | `data/README §五B` | token 聚合、报告字段 |
| **K3** | **Codex token 不摊到单次工具调用**（会话级单列） | `data/README §五D` | Codex 侧任何 per-tool token 结论 |
| **K4** | **Claude 侧按工具耗时不可得**，`duration_ms=None` + `duration_available=false`；**不得用 `lastToolDuration` 冒充** | `data/README §五B` | 耗时均值、报告样本量说明 |
| **K5** | **`settings.json` 的 `env` 是禁读键**；白名单只读 `permissions.allow` / `enabledPlugins` | `plan/02 §五`、`parsers/claude_config.py` | `tests/test_privacy.py`、`tests/test_parsers.py` |
| **K6** | **退出码语义**：0 成功 / 1 检出问题 / 2 用法 / 4 数据不可用（**3 已于 M2 退役**） | `exit_codes.py`、`plan/02 §六` | `test_cli.py`、`test_exit_codes.py`、README 退出码表 |
| **K7** | **确定性写盘契约**：`sort_keys=True` + `ensure_ascii=False` + LF + 结尾换行 + 原子写，**唯一入口 `serialize.py`** | `src/opslens/serialize.py` | `test_serialize.py`、所有产物双跑一致 |
| **K8** | **零第三方依赖 / 零出网 / 无时钟无随机**（stdlib 冻结名单在 `tests/test_discipline.py`） | `plan/02 §一/§五` | `test_discipline.py`（新增 stdlib 要同步进冻结名单，**M4 已加 `hashlib`**） |
| **K9** | **阈值/口径参数全在 `data/rules/*.json`**，代码零数值字面量（含 docstring/注释） | `plan/03 §4.1` | 零字面量门禁 |
| **K10** | **规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空 | `config.py`、`plan/03 §3.2` | `tests/test_rules_gate.py`、`test_attribute.py` |
| **K11** | **IR 排序键 = `(source, session_id, seq)`**，`seq` 是源行号，全程不读时钟 | `schema.py`、`parsers/` | 双跑逐字节一致 |
| **K12** | **真值库只存输入与期望**，观测由基准运行时实算（出现 `observed` 即红） | `plan/04 §3.2`、`bench.py` | 模块 5 基准有效性 |
| **K13** | **合成覆盖度 ≠ 已核对样例**：`synthetic_coverage` 只登记演练关系，**不得**写进 `verified_samples` | `data/rules/failure_patterns.json` | `test_rules_gate.py`、`test_synthetic_data.py` |
| **K14**（M2） | **schema 版本 = 显式集合**，不是正则放宽匹配；不在集内 → exit 4 + 打印检测键路径 | `parsers/versions.py` | `test_parsers.py` 版本断言、变异项 11/12 |
| **K15**（M3 新增） | **口径唯一性**：`BinOp(Div)` 只允许出现在 `aggregate.py` / `attribute.py` / **`bench.py`（M4 扩充）** / `tools/gen_synthetic_logs.py` | `tests/test_aggregate.py::DIV_ALLOWED_FILES` | 口径唯一性守门、变异项 19 |
| **K16**（M3 新增） | **`error_text` = 空白归一**（多行折叠为单行）+ 上限截断；**不是**只取首行 | `parsers/common.py::truncate_error_text` | `test_parsers.py`、`test_attribute.py`、变异项 23 |
| **K17**（M3 新增） | **归因只在 `error_text` 上匹配**，且**只消费 `status=="error"`** 的事件（成功与 unknown 都不参与） | `attribute.py` | `test_attribute.py`、变异项 22 |
| **K18**（M3 新增） | **重试期望必须可由日志复算**：合成数据按 server 形态分节奏（重试型在窗口内、其余在窗口外） | `tools/gen_synthetic_logs.py::_validate_retry_separation` | `test_aggregate.py` 重试对账、变异项 24 |
| **K19**（M4 新增） | **探活判定 = "重跑 check 且必须报差异"**；探活注入值从实算值派生（不是写死魔数）；未变红 = 假门 → exit 1 | `bench.py::_run_suite`、各 `_probe_*` | `test_bench.py`、变异项 25 |
| **K20**（M4 新增） | **"未启用"不冒充通过**：空分母 → `not_enabled=true` + notes + **exit 1**；且不计入通过数 | `bench.py::_run_suite`、各套件 `requirement` | `test_bench.py`、变异项 26 |
| **K21**（M4 新增） | **基准观测一律运行时实算**：`build_bundle()` 重新扫描+聚合+归因，与 `truth.json` 无数据通路 | `bench.py::build_bundle` | `test_bench.py::test_engine_output_is_computed_at_runtime_not_read_from_truth` |
| **K22**（M4 新增） | **计数级 F1 是聚合粒度**：`F1=1` 等价于逐 server 错误计数一致，**不等于**逐条分类质量（口径须如实标注） | `bench.py::_check_parse_baseline`、README、plan/03 §5.3 | `test_bench.py::test_parse_baseline_f1_is_one` |

### M4 的两条补充（**重要，别踩**）

1. **探活不能只是"再跑一遍对账"**：那样对"恒真的守门"毫无反应。必须**注入缺陷后重跑同一套 check
   并断言报出 ≥1 条差异**。本棒据此抓出自己 **3 个真假门**（首版断言只读派生载荷 `payload`/`metrics`，
   把守门改成恒真时不会红）——正解是**直接断言 `check()` 的 `diffs` 产出**，并各配一条阳性对照。
   探活的**注入值一律从实算值派生**：首版 `_probe_failure_rate` 写死"分母 36"，恰好等于正确分母 → 探活空转，
   被自己的探活机制当场抓出（基准自判未达标）。改为"正确分母 + `calls_unknown`"。
2. **M5 报告层绝不能再算比率**：`report/` 若出现 `BinOp(Div)` → 口径唯一性守门必红。
   报告的一切数字来自 `report.json`（而它来自 `aggregate` / `attribute` 载荷）。

---

## 四、本机环境坑（只写实测过的，M4 新增两条）

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
10. **产物确定性可用 sha256 跨进程复核**（M4 的 `B-E2E-DETERMINISM` 即此手法）。
11. **禁读键的守门要防"假变异"**：变异"没红"有两种可能——守门是假门，**或者变异本身是假的**；先判断是哪种。
12. **真实 server 名禁止词表会命中**文件名**（`installed` + `_plugins.json` 与一个真实 server 名同形）。
    **正解：运行时拼接构造**，**不是**把该词从禁止词表里删掉（放宽守门来迁就自己的代码是本末倒置）。
    ⚠️ **扫描面是全仓**：`test_real_server_names_absent_from_repo_content` 从仓库根 `os.walk`，
    故 **`plan/` 下的文件（含本交接文件）也在扫描面内**——写文档时若把某个真实 server 名写成字面量，
    会被自家守门判红（M1/M2/M3 各踩过一次）。豁免名单见 `tests/test_privacy.py::ALLOWED_MENTION_FILES`。
    **本文件即在该扫描面内**——M4 收尾时已实测通过。
13. **文件形态判别优于路径判别**：`discovery.py` 按**首行形态**判别解析器，真实布局与合成目录走同一条通路。
14. **`sqlite3` 窗口函数（`LAG` / `WINDOW`）本机双解释器都可用**（3.8.8 带 3.34.0，3.12 带 3.49.1）。
15. **"探针先行"能抓出真缺陷，别只写测试**：M3 的两个真实缺陷都是**先用一次性只读探针实测**才发现的。
    探针脚本用完即删（`tools/` 下会被编码守门扫到）。
16. **"期望值"与"实现"必须相互独立**：真值期望值若与引擎共用一份计算实现，就变成"引擎自证"（K12 明禁）。
17. **【M4 新增】"变异没红"要区分"守门是假门"与"断言读错了对象"**：本棒 M4 首版三条断言只读
    **派生载荷**（`payload` / `metrics`），而守门实现被改恒真时派生载荷**仍如实** → 变异不红。
    **正解：断言直接打在 `check()` 的 `diffs` 产出上**（那是守门的实际输出），并各配阳性对照。
18. **【M4 新增】探活是"基准的自我证伪"**：`bench` 不只跑一次对账，还对**每个套件**证明"弄坏了会红"。
    写新套件时**必须同时写 `probe`**，否则 `_run_suite` 会因"探活未变红"把该套件判为未达标
    （这是**有意的**——防"新加套件只写 check 不写探活"混过门）。

---

## 五、DoD 逐项 Checklist（M4 出口门，逐项已验）

- [x] `src/opslens/bench.py`：四层套件对账（样本驱动 6 + 规则驱动 3 + 覆盖声明 1 + 双基线 2）
- [x] **对账全维度一致**：`bench` → 12 套件 / **0 差异** / exit 0
- [x] **差异逐条列出**（维度 / 键 / 期望 / 实际；不是只报"不一致"）
- [x] **分层**：样本驱动层 + 规则驱动层；套件注册进 `--only` 白名单（唯一出处 `SUITES`）
- [x] **`bench --only NOPE` → exit 2**（实测：stderr 报未知套件 + 可用清单）
- [x] **每套件配可证伪探活**：12/12 逐个验证注入缺陷后必报差异
- [x] **退出码三语义（0/1/2）锁进测试**
- [x] **空分母分支**：空规则包 → `not_enabled=true` + notes + **exit 1**（"未启用"不冒充通过）
- [x] **覆盖声明"总数/采样数双登记" + 显式"抽样覆盖非穷举"**（基准消费 `manifest.json`）
- [x] **双基线复跑**：解析对账基线（F1 = 1）+ e2e 双跑逐字节一致（`bench --check` 可单独复跑）
- [x] `tests/` 全绿：**双解释器各 251 passed**
- [x] 变异验证 **30/30**（M1 十项 + M2 六项 + M3 八项 + M4 六项）
- [x] **HANDOFF-M5 落盘并 commit**（本文件）
- [ ] M5 交付报告 —— **下一棒（见 §二）**

**偏差说明（如实留档）**：
- **CI 未实跑**：本棒无远端。待 M6 首推验证。CI 已新增 bench 三条步骤（达标 / 未知名 exit 2 / 双基线复跑）。
- **本棒修正了自己 3 个真假门**（变异验证抓出）：首版 M4 断言只读派生载荷，守门改恒真时不红 →
  改为直接断言 `check()` 的 `diffs` 产出 + 阳性对照 + "探活判定必须是重跑 check 得出的"断言。
- **探活注入值从实算值派生**：首版 `_probe_failure_rate` 写死"分母 36"（恰等于正确分母）→ 探活空转，
  被自己的探活机制当场抓出。已改为派生值。
- **口径唯一性白名单扩为四处**（新增 `bench.py`）：基准算的是**解析质量指标**（precision/recall/F1），
  非域口径的第二份计算；落点只有 `_ratio()` 一处。扩充而非放宽，逐条论证见 `DIV_ALLOWED_FILES`。
- **`hashlib` 进 stdlib 冻结名单**（基准的 sha256 双跑复核）。
- **Codex 侧未建模重试**：真值只在 Claude 侧 6 server 声明 `expected_retry_count`；Codex 条目
  记 `undeclared` 并跳过比对（**不静默当作通过**）。
- **计数级 F1 是聚合粒度的**：真值为 server 级精确植入计数（非逐条标注）→ F1 = 1 等价于逐 server
  错误计数一致，**不等于**逐条分类质量。口径已写进 `metrics.definition` / README / plan/03 §5.3，不夸大。
- **`report` 仍未落地**：调用时按用法码 2 退出并明确报"本构建尚未包含"（M5 落地）。

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -X utf8 -m pytest -q

# 变异验证（M1 10 项 + M2 6 项 + M3 8 项 + M4 6 项）
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
py -X utf8 -m opslens bench                                               # → exit 0（12 套件 / 0 差异）
py -X utf8 -m opslens bench --check                                       # → exit 0（只跑双基线）
py -X utf8 -m opslens bench --only NOPE                                   # → exit 2
py -X utf8 -m opslens report --events events.json --out examples/         # → exit 2（M5 前尚未包含）
py -X utf8 -m opslens scan --home . --rules-dir ./nope                    # → exit 4（规则包缺失）

# 基准对账速查（M5 可复用：真值期望值已声明 expected_suggestion，报告层可直接消费）
py -X utf8 -c "
from opslens import bench
payload, code = bench.run_bench()
print('exit', code, 'verdict', payload['verdict'])
for item in payload['suites']:
    print(item['layer'], item['id'], item['status'], 'probe_detected=', item['probe']['detected'])
"
```

**扫描面清单**（新增文件时注意）：
- `tests/test_discipline.py::STDLIB_FROZEN` —— 新增 stdlib import 要同步进名单（**M4 已加 `hashlib`**）。
- `tests/test_discipline.py::SCAN_DIRS` = `src/` + `tools/`。
- `tests/test_aggregate.py::DIV_ALLOWED_FILES` —— `BinOp(Div)` 白名单（**M4 已加 `src/opslens/bench.py`**；新增落点须改测试）。
- `tests/test_privacy.py::REAL_SERVER_NAMES` / `REAL_SERVER_NAME_TOKENS` —— 真实 server 名禁止词表。
- `tests/test_privacy.py::ALLOWED_MENTION_FILES` —— 允许提及键名的台账文件白名单。
- `tests/test_encoding.py::_printable_entry_points` —— `tools/` 全部入口脚本的编码守门扫描面。
- `tests/test_readme_gate.py` —— README 命令/旗标/extras 与 CLI/pyproject 对账（**M5 增补 `report` 用法后须同步**）。
- `tests/test_parsers.py::FORBIDDEN_PARSER_IMPORTS` —— 解析层禁止 import 的模块清单。
- `tests/test_synthetic_data.py` —— 合成数据与生成器守门。

---

## 七、下一棒启动提示词

```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M5.md" 继续完成任务
```
