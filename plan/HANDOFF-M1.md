# HANDOFF-M1 · 交接（下一棒：M1 数据先行收尾 —— 合成数据与规则包）

> 用法：新对话 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务`
> 上一棒：M0 计划与骨架（✅ 2026-10-16 完成）。本文件写于 M0 收尾，指向 M1 剩余工作。

---

## 一、当前进度与证据（已完成的，别重做）

### 1.1 plan/ 与 data/ 文档齐备

| 文件 | 内容 |
|---|---|
| `plan/00-README总览.md` | 索引、决策记录、承诺-证据台账、里程碑状态 |
| `plan/01-题目文档.md` | 题目定稿（五模块、评分口径、边界） |
| `plan/02-架构与技术选型.md` | 分层架构、统一 IR、确定性/隐私设计、包布局 |
| `plan/03-模块详设.md` | 五模块详设 + 指标口径（**唯一出处**） |
| `plan/04-数据计划.md` | 数据资产台账、合成数据规格、真值植入 |
| `plan/05-里程碑.md` | M0–M6 与 DoD |
| `plan/06-交付对标.md` | 四栏评分对标 + **待定决策表 D1–D10** |
| `data/README.md` | 查证记录 + **§五 M1 字段语义实测结论（本棒最重要产出）** |

### 1.2 可运行骨架（已实测）

```
src/opslens/
  __init__.py(__version__="0.1.0")  __main__.py  _encoding.py  exit_codes.py
  schema.py(ToolCallEvent/三态/Tokens)  serialize.py(确定性写盘唯一入口)
  config.py(规则包加载+两态门控)  cli.py(argparse 五子命令)  tools/  tests/
data/rules/{thresholds,params,failure_patterns}.json
.github/workflows/ci.yml    pyproject.toml    README.md    .gitattributes
```

**证据（M0 出口门实跑记录）**：
- 双解释器全量测试：`py -X utf8 -m pytest -q` → **64 passed**；`py -3.12 -X utf8 -m pytest -q` → **64 passed**。
- CLI 冒烟：`opslens --version` → `opslens 0.1.0`；`--help` 列出 5 子命令；骨架期命令 → **exit 3**；缺规则包 → **exit 4**；无参数 → **exit 2**。
- **干净 venv 安装面实测**：`pip install -e ".[dev]"` 成功；**裸 `opslens` 在中立目录**（非仓库根）跑通；默认规则目录解析到仓库内 `data/rules`（存在）。
- **变异验证 5/5 通过**（每个守门故意弄坏 → 必红）：status 门 / samples 门 / 结尾换行 / `sort_keys` / 第三方 import 注入。其中发现并修复了一个真假门（CR 断言打在 `dumps()` 返回值上而非写盘字节上）。
- **CSV 口径一致性**：`data/README.md §五 E` 是模块 1→2→3 成败/token/耗时口径的唯一出处。

### 1.3 M1 字段语义核对：**已完成**（本棒核心）

已实测并入库（`data/README.md §五`）：
- **成败判定 `is_error` 是三态**：`True`/`False`/**字段缺失**。缺失占约 50%，其中 14.9% 含错误文本 → **只认 `True` 为失败，缺失一律 `unknown`，绝不默认为成功**。
- **token = 调用轮次归属**：在 assistant 消息的 `message.usage`（覆盖 100%），**不是工具自身开销**；缓存两项单列。
- **耗时：Claude 侧不可得**（无按工具字段）；Codex 侧可从 `Wall time:` 文本取。
- **Codex 无显式 error 标志**：只能用 `Exit code: N` 文本模式；`custom_tool_call.status` 恒为 `completed`（哑值，不可用）。
- **隐私红线**：`~/.claude/settings.json` 的 `env` 块含活体凭据 → 定为**禁读键**；白名单键位勘误为 `permissions.allow`。
- 检测键：Claude 顶层 `version`（实测 7 个版本）/ Codex `session_meta.cli_version`。

---

## 二、下一棒待办（M1 剩余 = 合成数据与规则包收尾）

按 `plan/05-里程碑.md` §M1 的 DoD 逐项做：

1. **`tools/gen_synthetic_logs.py`**（核心）
   - 自研 **splitmix64** 确定性 RNG（**禁 stdlib `random` / 禁 `set` 迭代序 / 禁系统时钟**——`tests/test_discipline.py` 会拦）。
   - 产出 `data/synthetic/logs/{claude_alpha.jsonl, codex_alpha.jsonl}` + `truth.json` + `manifest.json`。
   - server 名一律 `fake-*` 白名单（`fake-high-fail` / `fake-mid-fail` / `fake-low-fail` / `fake-retry`）；
     **真实 server 名进禁止词表**（`tests/test_privacy.py` 已扫描，命中即红）。
   - 覆盖度（写进 `manifest.json`，**总数/采样数双登记**）：4 失败率形态 + 4 失败模式 + **三态各 ≥1**（含 `is_error` 缺失样本）+ **threshold_exact / near_miss 边界** + **反向样例（低失败率 server 不该被建议移除）**。
   - `--check` 通路：重生成逐字节一致（写完立刻配守门测试）。
   - **编码守门**：脚本入口调 `_encoding.ensure_utf8_stdio()`（`tools/` 全覆盖，不只手守主 CLI）。
2. **`truth.json` 只存输入与期望**：**不得出现 `observed_*` / `engine_output` 一类字段**（配守门断言）。
   生成器启动时按 `data/README.md §四` 的失败判定口径植入真值，但**不得**把引擎将来会算的东西冻结进去。
3. **补 `verified_samples`**：`data/rules/failure_patterns.json` 里 `F-REFUSE-1`（content_refusal）当前 **0 样例 → pending**（这是**如实**的，本机 94 个日志里确实 0 条）。
   合成日志会植入该类记录，**但植入不能当"已核对样例"**（那是自证循环）——保持 pending，等真实样例。
4. **规则表补充**：给 `F-TIMEOUT-1` / `F-PERM-1` / `F-ARGS-1` 补挂从合成日志可验证的样例（注意样例来自真实实测，见 `data/rules/failure_patterns.json` 现有 `verified_samples`）。
5. **收尾**：DoD 验证 → 回写 `plan/00` / `plan/05` → 写 **`plan/HANDOFF-M2.md`** → commit。

---

## 三、既定口径清单（K 编号，"动了会打挂测试/基准"的约定）

| K | 口径 | 落点 | 动了会打挂什么 |
|---|---|---|---|
| **K1** | **成败三态**：只认 `is_error is True` 为 error；`False` 为 ok；**缺失 = unknown，不进失败率分母** | `data/README.md §五A/E`、`plan/03 §模块2.1` | 模块 2/3/4 全部计数与基准真值 |
| **K2** | **token = 调用轮次归属**，四项（input/output/cache_read/cache_creation）**分列不合并** | `data/README.md §五B`、`plan/03 §2.1` | token 聚合、报告字段、"总 token"表述 |
| **K3** | **Codex token 不摊到单次工具调用**（会话级单列） | `data/README.md §五D` | Codex 侧任何 per-tool token 结论 |
| **K4** | **Claude 侧按工具耗时不可得**，`duration_ms=None`；**不得用 `lastToolDuration` 冒充** | `data/README.md §五B`、`plan/03 §2.1` | 耗时均值、报告样本量说明 |
| **K5** | **`settings.json` 的 `env` 是禁读键**；白名单只读 `permissions.allow` / `enabledPlugins` | `plan/02 §五`、`plan/04 §二` | 隐私守门（`tests/test_privacy.py`）、解析器实现 |
| **K6** | **退出码语义**：0 成功 / 1 检出问题 / 2 用法 / 3 阶段未就绪（**退役型**）/ 4 数据不可用 | `src/opslens/exit_codes.py`、`plan/02 §六` | `tests/test_cli.py`、`tests/test_exit_codes.py`、README 退出码表 |
| **K7** | **确定性写盘契约**：`sort_keys=True` + `ensure_ascii=False` + LF + 结尾换行 + 原子写，**唯一入口 `serialize.py`** | `src/opslens/serialize.py` | `tests/test_serialize.py`、所有产物双跑一致 |
| **K8** | **零第三方依赖 / 零出网 / 无时钟无随机**（stdlib 冻结名单在 `tests/test_discipline.py`） | `plan/02 §一/§五` | `tests/test_discipline.py`（新增 stdlib 要同步进冻结名单） |
| **K9** | **阈值/口径参数全在 `data/rules/*.json`**，代码零数值字面量（含 docstring/注释） | `plan/03 §4.1`、`plan/04 §四` | 零字面量门禁、报告建议触发 |
| **K10** | **规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空，规则才生效；否则落 `other` 并在报告列原因 | `src/opslens/config.py`、`plan/03 §3.2` | `tests/test_rules_gate.py`（两条门各有独立变异验证） |
| **K11** | **IR 排序键 = `(source, session_id, seq)`，`seq` 是源行号**（不是数组下标），全程不读时钟 | `src/opslens/schema.py`、`plan/02 §三` | 双跑逐字节一致 |
| **K12** | **真值库只存输入与期望**，观测由基准运行时实算（真值里出现 `observed` 即红） | `plan/04 §3.2` | 模块 5 基准有效性 |

---

## 四、本机环境坑（只写实测过的）

1. **双 Python 通道可用**：`py -0p` → **3.8.8** 与 **3.12**。本机一律 `py -X utf8` 跑命令（中文控制台）；**3.9+ 语法在 3.8 直接 SyntaxError**，写代码守 3.8 底线（禁 `match`、禁 `X | Y` 类型标注、禁 `dict | dict`）。
2. **`ast.Index` 包装（3.8 特有，已踩）**：3.8 上 `node.slice` 是 `ast.Index(value=Constant)`，3.9+ 才是裸 `Constant`——**只认后者的 AST 探针在 3.8 上静默漏判**（本棒变异验证抓出过这个假门）。正解见 `tests/test_privacy.py::_string_key`。
3. **Git Bash `/tmp` 与 Windows Python 路径不通**：备份/临时文件一律用**工作区相对路径**。本棒实测：`cp file /tmp/x.bak` 看似成功、后续 `cp /tmp/x.bak file` 恢复**静默失败**，导致源码残留一次变异 —— **所有"改文件-跑测试-还原"的脚本用 try/finally，并在还原后断言字节一致**。
4. **变异脚本要"先断言变异生效"**：字符串替换失败时脚本会静默 no-op，"测试仍绿"看起来像"假门"，实际是没改到代码（本棒第一次变异即如此）。**替换前 assert marker 存在，替换后 assert 文件已变**。
5. **变异的 marker 别撞 docstring**：`serialize.py` 的 docstring 里也写了 `sort_keys=True`——按字符串替换会改到注释行、测试照常绿。**marker 要足够长以唯一定位代码行**。
6. **venv 通道（实测可用）**：`py -3.12 -m venv .venv --without-pip` → `./.venv/Scripts/python.exe -m ensurepip` → 再 `pip install setuptools wheel`，然后才能 `pip install -e ".[dev]"`（**缺 setuptools 时 editable 安装报 `BackendUnavailable: Cannot import 'setuptools.build_meta'`**，这是实测报错原文）。镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple` + `NO_PROXY="*" no_proxy="*"`。
7. **`.venv/` 已在 `.gitignore`**，勿提交；`__pycache__` 全程 `PYTHONDONTWRITEBYTECODE=1`（本仓库实测尚无 pyc 损坏，保持习惯）。
8. **扫描面非空要自证**：文本/文件扫描类守门必须断言"扫到的文件数 ≥ N"，否则目录写错 → 扫 0 个 → 永远绿。

---

## 五、DoD 逐项 Checklist（M0 出口门，逐项已验）

- [x] `plan/00–06` 六份齐全
- [x] `data/README.md` M1 字段语义结论入档（§五）
- [x] 包骨架可装：`pip install -e ".[dev]"` 后 **`opslens` 与 `python -m opslens` 两条通路**都能跑（含中立目录裸命令实测）
- [x] 退出码语义（0/1/2/3/4）落 `exit_codes.py` 并被测试锁定
- [x] UTF-8 入口守卫在位 + 编码测试（cp1252 桩反向自证）
- [x] `tests/` 全绿：**双解释器各 64 passed**
- [x] CI workflow 落盘（ubuntu/windows × 3.8/3.12 + `PYTHONUTF8=1`）—— **本地等价校验（未接远端，CI 待首推验证）**
- [x] 零依赖守门 + 零出网守门（AST 冻结名单）
- [x] 变异验证 5/5（含发现并修复 1 个真假门）
- [x] **HANDOFF-M1 落盘并 commit**（本文件）
- [ ] `tools/gen_synthetic_logs.py` + 合成数据 + 真值 —— **下一棒（见 §二）**

**偏差说明（如实留档）**：
- **CI 未实跑**：本棒无远端，`CI 绿` 一律写作"本地等价校验（未接远端，CI 待首推验证）"，替代证据 = 双解释器全量测试 + 裸 console script 中立目录实测 + 变异验证。**缺口**：ubuntu runner 行为、3.8/3.12 之外的矩阵差异本机测不了，待 M6 首推验证。
- **wheel 安装下的规则目录解析未验**（已记入 `plan/02 §七` 缺口）：editable/源码态实测通过；wheel 形态未测，M6 前须解决或写进 README"已知环境问题"。
- **M1 生成器未开工**：本棒聚焦"字段语义核对"（数据先行的前置），生成器按 §二 交给下一棒。

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -X utf8 -m pytest -q

# CLI 冒烟（源码态：先设 PYTHONPATH）
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens --help
py -X utf8 -m opslens scan --home .            # → exit 3（骨架期）
py -X utf8 -m opslens scan --home . --rules-dir ./nope   # → exit 4

# 干净 venv 安装面验证
py -3.12 -m venv .venv --without-pip
./.venv/Scripts/python.exe -m ensurepip
./.venv/Scripts/python.exe -m pip install setuptools wheel -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv/Scripts/python.exe -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
./.venv/Scripts/opslens.exe --version          # 裸 console script 通路

# 规则包核对
py -X utf8 -c "from opslens import config; r=config.load_rules(); print([x['id'] for x in r.effective_patterns()])"
```

**扫描面清单**（新增文件时注意）：
- `tests/test_discipline.py::STDLIB_FROZEN` —— 新增 stdlib import 要同步进名单。
- `tests/test_privacy.py::REAL_SERVER_NAMES` —— 真实 server 名禁止词表。
- `tests/test_privacy.py::ALLOWED_MENTION_FILES` —— 允许提及键名的台账文件白名单。
- `tests/test_readme_gate.py` —— README 命令/旗标/extras 与 CLI/pyproject 对账。

---

## 七、下一棒启动提示词

```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M1.md" 继续完成任务
```
