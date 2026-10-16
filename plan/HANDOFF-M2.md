# HANDOFF-M2 · 交接（下一棒：M2 解析层 —— 三解析器 + 版本检测 + exit 3 退役）

> 用法：新对话 `/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务`
> 上一棒：M1 数据先行（✅ 2026-10-16 完成）。本文件写于 M1 收尾，指向 M2。

---

## 一、当前进度与证据（已完成的，别重做）

### 1.1 M0 骨架（已实测，别重做）

- `plan/00–06` 六份齐备；`data/README.md` 含字段语义实测结论（§五）。
- 包骨架可装：`pip install -e ".[dev]"` 后 `opslens` 与 `python -m opslens` 两条通路都能跑。
- 退出码语义落 `exit_codes.py`；UTF-8 入口守卫在位；CI workflow 落盘（**未接远端，CI 待首推验证**）。

### 1.2 M1 合成数据与规则包（本棒完成，**产物可直接作为 M2 输入**）

```
tools/gen_synthetic_logs.py          # splitmix64 + 固定 seed + --check
tools/mutation_check.py              # 变异验证 10/10
data/synthetic/logs/claude_alpha.jsonl   # 394 行（Claude 形态）
data/synthetic/logs/codex_alpha.jsonl    # 27 行（Codex 形态）
data/synthetic/truth.json            # 只存输入与期望
data/synthetic/manifest.json         # 覆盖度双登记
data/rules/{failure_patterns,thresholds,params}.json
tests/test_synthetic_data.py         # 合成数据守门
```

**证据（M1 出口门实跑记录）**：
- 双解释器全量测试：`py -X utf8 -m pytest` → **106 passed**；`py -3.12 -X utf8 -m pytest` → **106 passed**。
- `--check` 位级一致（exit 0）+ **跨进程 sha256 复核一致** + 中立目录裸跑通过。
- **变异验证 10/10 通过**，并借它发现修复 1 个真假门（三态断言原先只查冻结产物，不查重生成结果）。

### 1.3 合成日志的字段形态（M2 解析器的**现成输入规格**）

生成器按本机实测形态建模，M2 解析器可直接对着它写：

**Claude 形态**（每会话：1 条 `system` 头 + N 组 `assistant`/`user` 配对）：
- `system`：`{type, subtype:"init", version, session_id, timestamp}` —— **`version` 是版本检测键**（合成值 `2.1.233`）。
- `assistant`：顶层含 `uuid` / `parentUuid` / `sessionId` / `session_id` / `timestamp` / `version` / `cwd` / `userType` / `isSidechain` / `message`；
  `message.content[]` 内是 `{type:"tool_use", id, name:"mcp__fake-*__tool_*", input}`；
  `message.usage` 含 `input_tokens` / `output_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens`。
- `user`：`message.content[]` 内是 `{type:"tool_result", tool_use_id, content}`；
  **`is_error` 键可能整个缺失**（三态第三态，缺失 ≠ 成功）；
  顶层另有 `toolUseResult`（含 `stdout` / `stderr` / `interrupted`）。
- 关联方式：`tool_use.id` ↔ `tool_result.tool_use_id`（合成数据已实测 **1:1 配对、0 悬空**）。

**Codex 形态**（`session_meta` 1 条 + `response_item` / `event_msg`）：
- `session_meta.payload.cli_version` = `0.146.0-alpha.3.1` —— **版本检测键**。
- 调用：`payload.type` ∈ `function_call` / `custom_tool_call`，带 `call_id` / `name`（**无 `mcp__` 前缀**）。
- 结果：`payload.type` ∈ `function_call_output` / `custom_tool_call_output`，`output` 是**字符串或 input_text 块列表**；
  成败只能从文本取：`Exit code: N`（**无该文本 = `unknown`**）；耗时从 `Wall time: N seconds` 取。
- token：只在 `event_msg/token_count` 的 `info.last_token_usage` / `total_token_usage`（**会话级，不摊到单调用**）。

---

## 二、下一棒待办（M2 = `plan/05 §M2` 的 DoD 逐项）

按 `plan/05-里程碑.md` §M2 做，顺序建议：

1. **`src/opslens/parsers/` 三解析器**（`claude_jsonl.py` / `claude_config.py` / `codex_rollout.py`）
   - 产出统一 IR `ToolCallEvent`（`src/opslens/schema.py`，**已存在，别改契约**）。
   - **纯函数**：不读规则包、不读时钟、不写盘（AST 守门断言）。
   - `seq` = **源行号**（不是数组下标），保证 `(source, session_id, seq)` 排序确定。
2. **成败三态（K1 硬口径）**：Claude 只认 `is_error is True` 为 error、`False` 为 ok、**缺失 = `unknown`**；
   Codex 只认 `Exit code` 非 0 为 error、无该文本 = `unknown`。
   **守门**：合成日志含 unknown 样本（已就绪），断言解析结果里 unknown 计数与 `truth.json` 一致。
3. **schema 版本检测**：检测键 Claude `version` / Codex `session_meta.cli_version`；不在支持集 → **exit 4** + 打印检测键路径。
   **变异验证**：把版本集合改成万能匹配 → 测试必红。
4. **`env` 禁读守门**：`claude_config.py` 只按白名单键读（`permissions.allow` / `enabledPlugins`），
   **不得出现 `env` 取值路径**（`tests/test_privacy.py::test_source_never_reads_the_env_block` 已扫描 `src/`）。
5. **双跑 IR 逐字节一致（K11 最硬形态）**：单元级 + 端到端双锁。
6. **退出码 `3`（阶段未就绪）整项退役**：删常量 → 改 CLI/测试（含 `not hasattr` 防复活）→ 改文档退出码表 → 改决策记录，**四处同步**。
   ⚠️ 注意：`tests/test_cli.py::test_skeleton_does_not_fake_results` 与 `tests/test_exit_codes.py::test_not_ready_is_a_retirable_semantic`
   在退役时必须一并改掉，否则会红。
7. **收尾**：DoD 验证 → 回写 `plan/00` / `plan/05` → 写 **`plan/HANDOFF-M3.md`** → commit。

---

## 三、既定口径清单（K 编号，**动了会打挂测试/基准**）

| K | 口径 | 落点 | 动了会打挂什么 |
|---|---|---|---|
| **K1** | **成败三态**：只认 `is_error is True` 为 error；`False` 为 ok；**缺失 = unknown，不进失败率分母** | `data/README.md §五A/E`、`plan/03 §模块2.1` | 模块 2/3/4 全部计数与基准真值 |
| **K2** | **token = 调用轮次归属**，四项（input/output/cache_read/cache_creation）**分列不合并** | `data/README.md §五B` | token 聚合、报告字段 |
| **K3** | **Codex token 不摊到单次工具调用**（会话级单列） | `data/README.md §五D` | Codex 侧任何 per-tool token 结论 |
| **K4** | **Claude 侧按工具耗时不可得**，`duration_ms=None`；**不得用 `lastToolDuration` 冒充** | `data/README.md §五B` | 耗时均值、报告样本量说明 |
| **K5** | **`settings.json` 的 `env` 是禁读键**；白名单只读 `permissions.allow` / `enabledPlugins` | `plan/02 §五`、`plan/04 §二` | `tests/test_privacy.py`、解析器实现 |
| **K6** | **退出码语义**：0 成功 / 1 检出问题 / 2 用法 / 3 阶段未就绪（**M2 退役**）/ 4 数据不可用 | `exit_codes.py`、`plan/02 §六` | `test_cli.py`、`test_exit_codes.py`、README 退出码表 |
| **K7** | **确定性写盘契约**：`sort_keys=True` + `ensure_ascii=False` + LF + 结尾换行 + 原子写，**唯一入口 `serialize.py`** | `src/opslens/serialize.py` | `test_serialize.py`、所有产物双跑一致 |
| **K8** | **零第三方依赖 / 零出网 / 无时钟无随机**（stdlib 冻结名单在 `tests/test_discipline.py`） | `plan/02 §一/§五` | `test_discipline.py`（新增 stdlib 要同步进冻结名单） |
| **K9** | **阈值/口径参数全在 `data/rules/*.json`**，代码零数值字面量（含 docstring/注释） | `plan/03 §4.1` | 零字面量门禁 |
| **K10** | **规则门控双条件**：`status=="verified"` **且** `verified_samples` 非空 | `config.py`、`plan/03 §3.2` | `tests/test_rules_gate.py` |
| **K11** | **IR 排序键 = `(source, session_id, seq)`**，`seq` 是源行号，全程不读时钟 | `schema.py`、`plan/02 §三` | 双跑逐字节一致 |
| **K12** | **真值库只存输入与期望**，观测由基准运行时实算（出现 `observed` 即红） | `plan/04 §3.2` | 模块 5 基准有效性 |
| **K13**（M1 新增） | **合成覆盖度 ≠ 已核对样例**：规则表的 `synthetic_coverage` 只登记演练关系，**不得**写进 `verified_samples` | `data/rules/failure_patterns.json` | `test_rules_gate.py`、`test_synthetic_data.py` |

---

## 四、本机环境坑（只写实测过的，M1 新增两条）

1. **双 Python 通道可用**：`py -0p` → **3.8.8** 与 **3.12**。一律 `py -X utf8` 跑命令；**3.9+ 语法在 3.8 直接 SyntaxError**（禁 `match`、禁 `X | Y` 类型标注、禁 `dict | dict`）。
2. **`ast.Index` 包装（3.8 特有）**：3.8 上 `node.slice` 是 `ast.Index(value=Constant)`，3.9+ 才是裸 `Constant`——正解见 `tests/test_privacy.py::_string_key`。
3. **Git Bash `/tmp` 与 Windows Python 路径不通**：临时文件一律用**工作区相对路径**；"改文件-跑测试-还原"必须 try/finally + 还原后断言字节一致。
4. **变异脚本要"先断言变异生效"**：替换前 assert marker 存在，替换后 assert 文件已变，还原后再 assert 字节一致。
5. **变异的 marker 别撞 docstring**，要足够长以唯一定位代码行。
6. **venv 通道**：`py -3.12 -m venv .venv --without-pip` → `ensurepip` → `pip install setuptools wheel` → 才能 `pip install -e ".[dev]"`（缺 setuptools 报 `BackendUnavailable`）。镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple` + `NO_PROXY="*" no_proxy="*"`。
7. **扫描面非空要自证**：文本/文件扫描类守门必须断言"扫到的文件数 ≥ N"，否则目录写错 → 扫 0 个 → 永远绿。
8. **【M1 新增】写扫描类守门时，自己的测试/脚本也在扫描面内**：本棒变异脚本首版把真实 server 名写成字面量 → 被自家禁止词表守门判红。**正解：运行时拼接构造**（如 `"windows" + "-" + "mcp"`）。
9. **【M1 新增】"只查冻结产物"的守门会漏掉生成器变异**：断言若只读盘上文件，把生成器改坏（如 unknown 洗成 ok）时**测试照常绿**。**正解：冻结产物 + 重生成结果两层都断言**（本棒变异验证实测抓出过这个真假门）。
10. **【M1 新增】产物确定性可用 sha256 跨进程复核**：`py -c "hashlib.sha256(open(p,'rb').read())"` 重生成前后比对，比"测试绿"更硬。

---

## 五、DoD 逐项 Checklist（M1 出口门，逐项已验）

- [x] `tools/gen_synthetic_logs.py`：自研 splitmix64、固定 seed、无时钟、无 stdlib `random`
- [x] 产出 `data/synthetic/logs/*.jsonl` + `truth.json` + `manifest.json`
- [x] `--check` 通路：重生成逐字节一致（守门测试 + CI 步骤）
- [x] `truth.json` 无 `observed` 类字段（守门断言）
- [x] 覆盖度：4 server 形态 + 4 失败模式 + 3 三态 + threshold_exact/near_miss + 反向样例；manifest 双登记
- [x] 规则包三件套落盘；`verified` 规则带 `verified_samples`；`F-REFUSE-1` 保持 pending
- [x] 禁止词表守门：真实 server 名 / 凭据值在仓内 0 命中
- [x] 编码守门覆盖 `tools/` 全部脚本
- [x] `tests/` 全绿：**双解释器各 106 passed**
- [x] 变异验证 **10/10**（含发现并修复 1 个真假门）
- [x] **HANDOFF-M2 落盘并 commit**（本文件）
- [ ] M2 三解析器 + 版本检测 + exit 3 退役 —— **下一棒（见 §二）**

**偏差说明（如实留档）**：
- **CI 未实跑**：本棒无远端，M1 新增的 `--check` CI 步骤只做过本地等价校验；缺口 = ubuntu runner 行为，待 M6 首推验证。
- **合成日志是"格式保真"非"真实分布"**：字段形态按本机实测建模，但数量与失败率是植入值；manifest 已声明"抽样覆盖，非穷举"。
- **wheel 安装下的规则目录解析仍未验**（见 `plan/02 §七`）：M1 生成器同样按"包外三级"定位 `data/rules`；wheel 形态未测，M6 前须解决或写进 README"已知环境问题"。

---

## 六、关键命令速查

```bash
# 测试（双解释器）
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -X utf8 -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 py -3.12 -X utf8 -m pytest -q

# 合成数据：重生成 / 位级校验 / 变异验证
py -X utf8 tools/gen_synthetic_logs.py --out data/synthetic
py -X utf8 tools/gen_synthetic_logs.py --check
py -X utf8 tools/mutation_check.py

# CLI 冒烟（源码态：先设 PYTHONPATH）
export PYTHONPATH="$PWD/src"
py -X utf8 -m opslens --help
py -X utf8 -m opslens scan --home .            # → exit 3（骨架期；M2 退役该语义）
py -X utf8 -m opslens scan --home . --rules-dir ./nope   # → exit 4

# 规则包核对
py -X utf8 -c "from opslens import config; r=config.load_rules(); print([x['id'] for x in r.effective_patterns()]); print(r.ineffective_patterns())"

# 产物 sha256（跨进程确定性复核）
py -X utf8 -c "import hashlib; print(hashlib.sha256(open('data/synthetic/truth.json','rb').read()).hexdigest())"
```

**扫描面清单**（新增文件时注意）：
- `tests/test_discipline.py::STDLIB_FROZEN` —— 新增 stdlib import 要同步进名单。
- `tests/test_privacy.py::REAL_SERVER_NAMES` / `REAL_SERVER_NAME_TOKENS` —— 真实 server 名禁止词表（分"裸子串"与"`mcp__<name>__` 命名空间"两类）。
- `tests/test_privacy.py::ALLOWED_MENTION_FILES` —— 允许提及键名的台账文件白名单。
- `tests/test_encoding.py::_printable_entry_points` —— `tools/` 全部入口脚本的编码守门扫描面。
- `tests/test_readme_gate.py` —— README 命令/旗标/extras 与 CLI/pyproject 对账。
- `tests/test_synthetic_data.py` —— 合成数据与生成器守门（`--check` 位级、真值无观测字段、覆盖度双登记、三态保真）。

---

## 七、下一棒启动提示词

```
/goal 读取 "<项目绝对路径>\plan\HANDOFF-M2.md" 继续完成任务
```
