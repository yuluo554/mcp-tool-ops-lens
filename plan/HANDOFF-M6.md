# HANDOFF-M6 · 交接（下一棒：M6 脱敏发布 —— GitHub 公开仓库 + tag + Release）

> 用法：新对话 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务`
> 上一棒：M5 交付（✅ 2026-10-16 完成）。本文件写于 M5 收尾，指向 M6。

---

## 一、当前进度与证据（已完成的，别重做）

### 1.1 M0–M4（已实测，别重做）

- `plan/00–06` 六份齐备；`data/README.md` 含字段语义实测结论（§五）。
- 包骨架可装；退出码语义落 `exit_codes.py`（**`3` 已退役**）；UTF-8 入口守卫在位；CI workflow 落盘（**未接远端**）。
- M1：`tools/gen_synthetic_logs.py`（splitmix64 + 固定 seed + `--check`）、`data/synthetic/{logs,truth.json,manifest.json}`、`data/rules/*.json`。
- M2：`src/opslens/parsers/`（三解析器 + 版本检测 + 发现逻辑）、`pipeline.py`（scan 阶段）。
- M3：`src/opslens/aggregate.py`（sqlite3 两级聚合）、`src/opslens/attribute.py`（五分类规则匹配）。
- M4：`src/opslens/bench.py`（四层 12 套件 + 每套件可证伪探活 + 退出码 0/1/2）、`tools/mutation_check.py`。

### 1.2 M5 交付（本棒完成，**产物可直接作为 M6 的发布素材**）

```
src/opslens/report/__init__.py    # 模块 4：单一渲染源 report.json 装配 + 三产物落盘 + 退出码
src/opslens/report/suggestions.py # 建议层（阈值全参数注入；证据完整性硬门；样本不足降级）
src/opslens/report/markdown.py    # MD 渲染器（零判定；渲染出口常驻无外链断言）
src/opslens/report/html.py        # HTML 渲染器（内联 CSS、零外链）
src/opslens/report/guard.py       # assert_no_external_resources 的常驻落点
src/opslens/cli.py                # report 子命令接通（IMPLEMENTED_COMMANDS 五命令齐备）
src/opslens/pipeline.py           # report_events 编排阶段（零判定转交）
tests/test_report.py              # 报告层守门（29 条）
tools/mutation_check.py           # M5 六项变异（总 36 项）
examples/{report.json,report.md,report.html}  # 入仓示例报告（基于合成数据）
.github/workflows/ci.yml          # 新增 report 两条 CI 步骤（产物+零外链 / 示例重生成比对）
README.md                         # 状态行转正 + report 用法 + 报告层口径节
```

**证据（M5 出口门实跑记录）**：
- 双解释器全量测试：`py -X utf8 -m pytest` → **284 passed**；`py -3.12 -X utf8 -m pytest` → **284 passed**。
- **五模块闭环齐备**：`IMPLEMENTED_COMMANDS == ("scan","aggregate","attribute","report","bench")`，
  与注册子命令集**逐一对应**（守门断言 `set(IMPLEMENTED_COMMANDS) == set(子命令)`）。
- **三产物双跑逐字节一致**：`report.json` / `report.md` / `report.html` 两次独立运行 sha256 相同
  （`ec6b44a8…` / `e1ccaf0e…` / `17badb06…`）；入仓示例 == 由 `data/synthetic` 重生成结果（守门 + CI 双重比对）。
- **渲染层零判定**：口径唯一性扫描面 **26 个文件**（含 `report/` 五文件），`BinOp(Div)` **0 违规**；
  `report/` 不 import 聚合/归因/基准/规则层。
- **无外链**：三份产物零外链构造；断言**常驻渲染出口**，用"注入外链载荷"证伪其真在出口生效。
- **断网 e2e 演示**：`socket.connect` / `getaddrinfo` 打死跑完整链路 → `scan=0` / `report=1` / `bench=0` /
  `bench --only NOPE=2`，**出网尝试 0 次**。
- **退出码逐条实测**：`report` 命中建议移除 → `1`；无 → `0`；事件流缺失/为空/规则包缺失 → `4`。
- **建议与植入真值对账**：6 个 Claude server 的失败轴标签与 `truth.json::expected_suggestion` **逐 server 相等**；
  "建议移除"集合与真值声明集合逐项一致。
- **变异验证 36/36 通过**（M1 十项 + M2 六项 + M3 八项 + M4 六项 + M5 六项）。

### 1.3 五模块通路现状（M6 演示用的完整命令面）

```bash
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens scan      --home data/synthetic --out events.json   # → exit 0
py -X utf8 -m opslens aggregate --events events.json --out agg.json       # → exit 0
py -X utf8 -m opslens attribute --events events.json --out attr.json      # → exit 0
py -X utf8 -m opslens report    --events events.json --out examples/      # → exit 1（检出"建议移除"）
py -X utf8 -m opslens bench                                               # → exit 0（12 套件 / 0 差异）
py -X utf8 -m opslens bench --check                                       # → exit 0（只跑双基线）
py -X utf8 -m opslens bench --only NOPE                                   # → exit 2
```

**`report.json` 结构**（`opslens.report/1`，单一渲染源）顶层键：
`schema` / `inputs`（含 `rate_precision`）/ `source_declaration` / `unknown_partition` /
`failure_attribution` / `server_metrics` / `tool_metrics` / `rankings` / `suggestions` /
`insufficient_data` / `positioning` / `summary`。

---

## 二、下一棒待办（M6 = `plan/05 §M6` 的 DoD 逐项）

按 `plan/05-里程碑.md` §M6 做，顺序建议：

1. **干净环境验证**：裸 clone + 全新 venv 按 README 逐条跑通，**退出码语义逐条记录**（留档 `plan/verify/README.md`）。
2. **脱敏四步 + 产物扫描 + 提交元数据邮箱检查留档**（命令 + 结论）。
3. **`git status` / `git log` / `rev-list --count` 三连核对**（**历史 = 工作树**）。
4. **建远端仓并首推**（D7：M6 才建仓；首推 CI 需预算诊断轮）。
5. **CI 首跑全绿 + `gh run list` 与 push/tag 事件按 `head_sha` 逐条配对**（同 sha 双 run 判 `event` + `head_branch`）。
6. **tag + Release（经用户确认）** + `plan/RELEASE-M6.md`；**三件套缺一即为未达成**：
   `git tag` + GitHub Release（附产物）+ 发布留档 `plan/RELEASE-M6.md`。
7. **发布物本体已验**：下载件 sha256 对账 + 中立目录自检。
8. **收尾固化**：README 状态行转正、topics、缓议项逐条全表清零。

---

## 三、既定口径清单（K 编号，**动了会打挂测试/基准**）

| K | 口径 | 落点 | 动了会打挂什么 |
|---|---|---|---|
| **K1** | **成败三态**：只认 `is_error is True` 为 error；`False` 为 ok；**缺失 = unknown，不进失败率分母** | `data/README §五A/E`、`parsers/claude_jsonl.py`、`aggregate.py` | 模块 2/3/4/5 全部计数与基准真值 |
| **K2** | **token = 调用轮次归属**，四项分列不合并 | `data/README §五B` | token 聚合、报告字段 |
| **K3** | **Codex token 不摊到单次工具调用**（会话级单列） | `data/README §五D` | Codex 侧任何 per-tool token 结论 |
| **K4** | **Claude 侧按工具耗时不可得**，`duration_ms=None` + `duration_available=false` | `data/README §五B` | 耗时均值、报告样本量说明 |
| **K5** | **`settings.json` 的 `env` 是禁读键**；白名单只读 `permissions.allow` / `enabledPlugins` | `plan/02 §五`、`parsers/claude_config.py` | `tests/test_privacy.py`、`test_parsers.py` |
| **K6** | **退出码语义**：0 成功 / 1 检出问题 / 2 用法 / 4 数据不可用（**3 已于 M2 退役**） | `exit_codes.py`、`plan/02 §六` | `test_cli.py`、`test_exit_codes.py`、README 退出码表 |
| **K7** | **确定性写盘契约**：`sort_keys=True` + `ensure_ascii=False` + LF + 结尾换行 + 原子写，唯一入口 `serialize.py` | `src/opslens/serialize.py` | `test_serialize.py`、所有产物双跑一致 |
| **K8** | **零第三方依赖 / 零出网 / 无时钟无随机**（stdlib 冻结名单在 `tests/test_discipline.py`） | `plan/02 §一/§五` | `test_discipline.py` |
| **K9** | **阈值/口径参数全在 `data/rules/*.json`**，代码零数值字面量 | `plan/03 §4.1` | 零字面量门禁（**M5 报告层亦在此门内**） |
| **K10** | **规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空 | `config.py`、`plan/03 §3.2` | `test_rules_gate.py`、`test_attribute.py` |
| **K11** | **IR 排序键 = `(source, session_id, seq)`**，`seq` 是源行号，全程不读时钟 | `schema.py`、`parsers/` | 双跑逐字节一致 |
| **K12** | **真值库只存输入与期望**，观测由基准运行时实算 | `plan/04 §3.2`、`bench.py` | 模块 5 基准有效性 |
| **K13** | **合成覆盖度 ≠ 已核对样例** | `data/rules/failure_patterns.json` | `test_rules_gate.py`、`test_synthetic_data.py` |
| **K14** | **schema 版本 = 显式集合**，不在集内 → exit 4 | `parsers/versions.py` | `test_parsers.py`、变异项 11/12 |
| **K15** | **口径唯一性**：`BinOp(Div)` 只允许出现在 `aggregate.py` / `attribute.py` / `bench.py` / `tools/gen_synthetic_logs.py` | `tests/test_aggregate.py::DIV_ALLOWED_FILES` | 口径唯一性守门、变异项 19/32 |
| **K16** | **`error_text` = 空白归一** + 上限截断（**不是**只取首行） | `parsers/common.py::truncate_error_text` | `test_parsers.py`、`test_attribute.py`、变异项 23 |
| **K17** | **归因只在 `error_text` 上匹配**，且**只消费 `status=="error"`** | `attribute.py` | `test_attribute.py`、变异项 22 |
| **K18** | **重试期望必须可由日志复算**（分节奏） | `tools/gen_synthetic_logs.py::_validate_retry_separation` | `test_aggregate.py`、变异项 24 |
| **K19** | **探活判定 = "重跑 check 且必须报差异"**；注入值从实算值派生 | `bench.py::_run_suite`、各 `_probe_*` | `test_bench.py`、变异项 25 |
| **K20** | **"未启用"不冒充通过**：空分母 → `not_enabled=true` + notes + **exit 1** | `bench.py::_run_suite` | `test_bench.py`、变异项 26 |
| **K21** | **基准观测一律运行时实算** | `bench.py::build_bundle` | `test_bench.py` |
| **K22** | **计数级 F1 是聚合粒度**（口径须如实标注） | `bench.py::_check_parse_baseline`、README | `test_bench.py` |
| **K23**（M5 新增） | **单一渲染源 `report.json`**：MD/HTML 都由它渲染，"两格式一致"是结构性质 | `report/__init__.py`、`report/markdown.py`、`report/html.py` | `test_report.py::test_md_and_html_render_from_the_same_payload` |
| **K24**（M5 新增） | **渲染层零判定**：`report/` 无 `BinOp(Div)`、不 import 聚合/归因/基准/规则层 | `report/` 五文件 | `test_report.py` 两条 AST 守门、变异项 32/35 |
| **K25**（M5 新增） | **无外链断言常驻渲染出口**（不是测试里验一次） | `report/guard.py` + 两个渲染器返回前 | `test_report.py::test_guard_is_load_bearing_at_the_render_exit`、变异项 31 |
| **K26**（M5 新增） | **建议证据完整性硬门**：缺任一项 → 该条不输出（视为内部错误） | `report/suggestions.py::assert_evidence_complete` | `test_report.py`、变异项 34 |
| **K27**（M5 新增） | **样本不足一律降级"数据不足"**，绝不出"建议移除" | `report/suggestions.py::_failure_axis` | `test_report.py`、变异项 33 |
| **K28**（M5 新增） | **`report` 退出码**：命中"建议移除" → 1，否则 0 | `report/__init__.py::exit_code_for`、`cli.py` | `test_report.py` 两条退出码断言 |

---

## 四、本机环境坑（只写实测过的，M5 新增三条）

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
9. **"只查冻结产物"的守门会漏掉生成器变异**：**正解：冻结产物 + 重生成结果两层都断言**
   （M5 的 `test_committed_examples_are_byte_identical_to_regeneration` 即此手法）。
10. **产物确定性可用 sha256 跨进程复核**。
11. **禁读键的守门要防"假变异"**：变异"没红"有两种可能——守门是假门，**或者变异本身是假的**；先判断是哪种。
12. **真实 server 名禁止词表会命中**文件名**。**正解：运行时拼接构造**。
    ⚠️ **扫描面是全仓**：`test_real_server_names_absent_from_repo_content` 从仓库根 `os.walk`，
    故 **`plan/` 下的文件（含本交接文件）也在扫描面内**——写文档时若把某个真实 server 名写成字面量，
    会被自家守门判红。豁免名单见 `tests/test_privacy.py::ALLOWED_MENTION_FILES`。
13. **文件形态判别优于路径判别**：`discovery.py` 按**首行形态**判别解析器。
14. **`sqlite3` 窗口函数（`LAG` / `WINDOW`）本机双解释器都可用**。
15. **"探针先行"能抓出真缺陷，别只写测试**：探针脚本用完即删（`tools/` 下会被编码守门扫到）。
16. **"期望值"与"实现"必须相互独立**：共用一份计算实现 = "引擎自证"（K12 明禁）。
17. **"变异没红"要区分"守门是假门"与"断言读错了对象"**：正解是断言直接打在守门的**实际输出**上。
18. **探活是"基准的自我证伪"**：写新套件时必须同时写 `probe`。
19. **【M5 新增】AST 守门的探针自证不能只测一种写法**：M5 首版"禁止 import"检测只查 `node.module`，
    **静默漏判** `from .. import aggregate`（`module is None`，名字在 `names` 里）与
    `from opslens import config`（子模块名在 `names` 里）两种形态。**正解：按所属包解析相对层级，
    且 `from X import Y` 同时产出 `X` 与 `X.Y` 两个候选**（AST 无法区分"子模块"与"包内名字"）。
20. **【M5 新增】改渲染文案 ≠ 改数据**：把某个数据块从报告里"抹掉"的变异，若只改渲染器的标题/前缀文案，
    数据仍会从别处露出 → 守门不红（**假变异**）。**正解：按"载荷装配处"变异**（把该数据字段置空），
    那才是"报告不再列出该清单"的真实故障形态。
21. **【M5 新增】堵网络别堵 `socket.socket` 这个类**：首版断网探针把 `socket.socket` 整个替换成函数，
    导致 stdlib 的 `ssl` 模块 import 失败（`class SSLSocket(socket)` → TypeError）——
    那是**探针自身坏了**，不是被测代码出网。**正解：堵 `socket.socket.connect` 与 `socket.getaddrinfo`**
    （出网的必经点，且不破坏 stdlib 自身 import）。
22. **【M5 新增】示例报告里的路径要可移植**：`examples/report.json` 的 `home` 用**仓库相对路径**
    （`data/synthetic`），故重生成比对时必须以**同样的相对路径**扫描（测试里 `os.chdir(REPO_ROOT)`），
    否则绝对路径会与冻结产物不一致 → 假红。

---

## 五、DoD 逐项 Checklist（M5 出口门，逐项已验）

- [x] **单一渲染源 `report.json`**：MD/HTML 都由它渲染（内容一致是结构性质）
- [x] **渲染层零判定**：AST 断言 `report/` 无 `BinOp(Div)`（26 文件扫描 / 0 违规）、不 import 引擎层
- [x] **无外链硬断言**：`assert_no_external_resources` **常驻渲染出口**（用注入外链载荷证伪其生效）
- [x] 报告必含：来源与覆盖声明 / `unknown` 独立分区 / 建议附口径+阈值+分子分母+样本量 /
    未生效规则清单（原因）/ 定位宣言 + "建议仅供参考，不自动修改配置"
- [x] **数据不足降级"数据不足"**（不出建议）：样本门是真门（阳性对照：抬到门槛之上立刻出建议）
- [x] **README ↔ CLI 对账守门**（`build_parser()` 反射）；README 安装行 extras 与 CI 一致
- [x] `examples/report.md` / `report.html` / `report.json` 入仓（基于合成数据）
- [x] **断网 e2e 演示通过**；退出码语义按 README 明示逐条记录（0/1/2/4 全实测）
- [x] **编码守门覆盖所有可打印入口**（主 CLI + `tools/` 全部脚本）
- [x] `tests/` 全绿：**双解释器各 284 passed**（M6 后为 **285 passed**，见下）
- [x] 变异验证 **36/36**（M1 十项 + M2 六项 + M3 八项 + M4 六项 + M5 六项）
- [x] **HANDOFF-M6 落盘并 commit**（本文件）
- [x] **M6 发布 —— 本棒完成**（✅ 2026-10-16，见 `plan/RELEASE-M6.md`）
  - 公开仓 https://github.com/yuluo554/mcp-tool-ops-lens · tag `v0.1.0` · Release 附源码 zip · CI 四矩阵绿

**M6 出口门实跑记录（2026-10-16，终版收官）**：
- **干净环境验证**：裸 clone + 全新 venv 按 README 逐条跑通，11 条命令退出码全部符合明示语义
  （留档 `plan/verify/README.md`）。抓出 2 个真实缺陷并修复：3.8 自带 pip 无法可编辑安装；wheel 不含规则包。
- **脱敏四步 + 产物扫描 + 元数据邮箱**：0 硬门命中；元数据邮箱已是 GitHub noreply（**无需历史重写**）。
  四步固化为入仓工具 `tools/audit_desensitize.py`（selftest 阳性/阴性对照 + 无 git 兜底）。
- **CI**：首跑 1 轮红（**CI 步骤 `set -e` 与 report 契约退出码 1 接线缺陷**，四矩阵同点）→ 修复即绿；
  截至终态 9 个 run，push 事件数 = run 数，同 sha 双 run 靠 `event`+`head_branch` 区分（tag push **会**触发）。
- **tag + Release**：经用户确认后执行（三件套齐备）；发布物本体复核（真下载 + sha256 对账 + 中立目录自检）
  抓出审计器**无 git 兜底**缺陷 → 零消费者窗口内修复 + 重建附件 + 迁移 tag + 复验。
- **测试**：**285 passed**（双解释器）；变异 **41/41**（M1 十项 + M2 六项 + M3 八项 + M4 六项 + M5 六项 + M6 五项）。

**偏差说明（如实留档）**：
- **CI 未实跑**：本棒无远端。待 M6 首推验证。CI 已新增 report 两条步骤（报告产物 + 零外链硬门 /
  入仓示例重生成逐字节比对）。
- **本棒修正了自己 2 个假门 + 1 个假变异**（探针自证与变异验证抓出）：
  1. 禁止 import 守门的探针只查 `node.module` → 漏判两种 import 形态（见 §四 item 19）。
  2. "未生效规则清单消失"变异项首版是假变异（只改渲染文案，见 §四 item 20）。
- **示例报告的事件流中间件不入仓**：`examples/` 只放三份报告产物；`events.json`（118KB）可由
  `data/synthetic` 确定性重建，CI 与守门测试均**重生成后逐字节比对**。
- **报告层"数据来源"节消费 scan 产物载荷**：`report --events` 从事件流 JSON 里读
  `home` / `sources` / `schema_versions`；缺字段即如实声明为空，**绝不回落到自动发现**。
- **`duration_missing` 汇总由报告层按 server 行求和**（聚合载荷 `totals` 未含该键）：
  那是计数求和、非比率，不违反"渲染层零判定"。
- **`report --out` 是目录、`bench --out` 是文件**：README 与帮助文本均已区分说明。
- **M6 是唯一"必须经用户确认"的里程碑**：建远端仓 + tag + Release 属外向且不可逆操作，
  动手前须确认（见 plan/05 §M6 DoD 的"经用户确认"）。

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -X utf8 -m pytest -q

# 变异验证（M1 10 + M2 6 + M3 8 + M4 6 + M5 6 = 36 项）
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
py -X utf8 -m opslens report    --events events.json --out examples/      # → exit 1（检出建议移除）
py -X utf8 -m opslens bench                                               # → exit 0（12 套件 / 0 差异）
py -X utf8 -m opslens bench --check                                       # → exit 0
py -X utf8 -m opslens bench --only NOPE                                   # → exit 2
py -X utf8 -m opslens report --events missing.json --out out              # → exit 4
py -X utf8 -m opslens scan --home . --rules-dir ./nope                    # → exit 4

# 示例报告重生成比对（CI 同口径）
py -X utf8 -m opslens scan --home data/synthetic --out ci-events.json
py -X utf8 -m opslens report --events ci-events.json --out ci-report
cmp ci-report/report.md examples/report.md && cmp ci-report/report.html examples/report.html \
  && cmp ci-report/report.json examples/report.json

# 断网可开自证（产物零外链）
grep -E "https?://|<link|<script|<img|@import" examples/report.html examples/report.md || echo "clean"
```

**扫描面清单**（新增文件时注意）：
- `tests/test_discipline.py::STDLIB_FROZEN` —— 新增 stdlib import 要同步进名单。
- `tests/test_discipline.py::SCAN_DIRS` = `src/` + `tools/`。
- `tests/test_aggregate.py::DIV_ALLOWED_FILES` —— `BinOp(Div)` 白名单（**M5 未扩充**：报告层必须无除法）。
- `tests/test_report.py::_report_py_files` —— 报告层 AST 守门扫描面（`src/opslens/report/*.py`）。
- `tests/test_privacy.py::REAL_SERVER_NAMES` / `REAL_SERVER_NAME_TOKENS` —— 真实 server 名禁止词表。
- `tests/test_privacy.py::ALLOWED_MENTION_FILES` —— 允许提及键名的台账文件白名单。
- `tests/test_encoding.py::_printable_entry_points` —— `tools/` 全部入口脚本的编码守门扫描面。
- `tests/test_readme_gate.py` —— README 命令/旗标/extras 与 CLI/pyproject 对账（**M5 已同步 report**）。
- `tests/test_parsers.py::FORBIDDEN_PARSER_IMPORTS` —— 解析层禁止 import 的模块清单。

---

## 七、下一棒启动提示词

```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M6.md" 继续完成任务
```
