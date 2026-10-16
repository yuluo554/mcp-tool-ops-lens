# plan/RELEASE-M6.md · 发布留档（M6 脱敏发布）

> 项目：`mcp-tool-ops-lens`（MCP/工具调用失败率与上下文开销归因 CLI）
> 版本：v0.1.0 · 发布日：2026-10-16 · 仓库：https://github.com/yuluo554/mcp-tool-ops-lens
> 口径纪律：CI 类结论**只记实测到的**；"首跑失败"与"修复提交"成对留档，不遮掩。
> **数字会随动作过期**——本文件的 run 计数为"截至某提交的快照"，权威口径见各节的**可复跑规则**。

---

## 一、干净环境验证（DoD 第 1 项）

**结论：通过。** 详细留档见 `plan/verify/README.md`（退出码逐条成表）。

- 裸 clone（`git clone --no-local`）+ 全新 venv，按 README 逐条执行 11 条命令，**退出码全部符合明示语义**
  （`scan/aggregate/attribute`=0、`report`=**1**（检出建议移除）、`bench`=0、`bench --only NOPE`=**2**、
  `scan --rules-dir ./nope`=**4**、`gen_synthetic_logs --check`=0）。
- 示例报告重生成与入仓 `examples/` **逐字节一致**；零外链硬门 `CLEAN`。
- 中立目录（仓库树外）`python -m opslens --help` / 裸 `opslens --help` 均 exit 0。

**本轮干净环境验证抓出 2 个真实缺陷（已修复，均非推测）**：
1. **Python 3.8 全新 venv 自带 pip 20.2.3 无法可编辑安装 pyproject-only 项目**（exit 1）→ README 补
   `python -m pip install -U pip` 前置行；安装段统一 `python -m pip` 并提示已激活 venv 时勿用 `py` 启动器。
2. **wheel（非 editable）安装下规则目录解析不到**（exit 4，`规则目录不存在`；wheel 不含 `data/rules`）
   → 按 `plan/02 §七` 写进 README **"已知环境问题"**节，声明首期发布物为源码包 + editable 安装。
   **未**写成"已验证 wheel 安装"。

**测试面**：干净 clone + 全新 venv **285 passed**；双解释器（3.8/3.12）各 **285 passed**；
CI 检出形态（`--depth 1 --no-tags`）**285 passed**（本仓库测试不依赖 git 元数据）。

## 二、脱敏四步 + 产物扫描 + 提交元数据邮箱（DoD 第 2 项）

**结论：四步 0 硬门命中。** 命令与结论：

| 步 | 命令 | 结论 |
|---|---|---|
| 1 文件名 | `git ls-files \| grep -iE "\.env$\|\.key$\|secret\|token"` | 空（73 个跟踪文件无命中） |
| 2 内容级 | `py -X utf8 tools/audit_desensitize.py`（第 2 步） | 73 个文本文件 0 命中 |
| 3 二进制 | 同审计器第 3 步（ASCII + UTF-16LE 双编码） | 0 个二进制跟踪文件（本项目无入仓二进制） |
| 4 全历史 | 同审计器第 4 步（逐 commit 迭代读 blob） | 11 个提交 0 命中；机制探活（仓库名在首提交命中）通过 |
| 元数据 | `git log --format="%ae %ce" --all \| sort -u` | 唯一值 = **GitHub noreply**（`<id>+yuluo554@users.noreply.github.com`） |

- **四步固化为入仓工具** `tools/audit_desensitize.py`（selftest 阳性/阴性对照；浅克隆下显式 exit 2 报 INCOMPLETE
  而非静默空扫；输出掩码化不回显原文；模式片段拼接构造，工具自身过自身扫描 0 命中）。
- **产物扫描**：本项目发布物为**纯源码包**（无 exe/dist），发布 zip 的**打包面 = git 跟踪面**
  （未跟踪杂项天然排除）；zip 的 sha256 见 §四。
- **提交元数据邮箱无需改写**：实测全部 9+ 提交的 `ae`/`ce` 均为 noreply（本机 `git config user.email` 已同步为
  noreply；全局配置虽是 QQ 邮箱，但历次提交未中招）——**无历史重写动作，故无 sha 失效问题**。

## 三、git 三连核对（DoD 第 3 项，**历史 = 工作树**）

| 检查 | 结果 |
|---|---|
| `git status` | clean（无未提交改动） |
| `git log --oneline` | 到 M6 收尾为止的线性历史，各里程碑一笔 |
| `git rev-list --count HEAD` | 与工作树一致（无"历史落后于工作树"漂移） |

> 本项为"改写前的必查"（租赁审计器 M6 实录：历史只到 M1、M2–M5 仅在暂存区）。
> 本项目每棒收尾均 commit，**未出现漂移**。

## 四、建远端 + 首推 + CI（DoD 第 4/5 项）

**建仓**：`gh repo create yuluo554/mcp-tool-ops-lens --public --source . --remote origin`（**不带 `--push`**）
→ 切 SSH（token scopes 无 `workflow`，HTTPS push 会被拒）→ `git remote set-url origin git@github.com:…` → push 一次成。

**CI 首跑实录（预算内的诊断轮，如实留档）**：

| run id | head_sha | event | 结果 | 说明 |
|---|---|---|---|---|
| 38913530971 | `96418426` | push | **failure**（4/4 矩阵同点红） | "示例报告重生成比对"步骤用 `set -e` 直接串，`report` 按契约退出码 **1** 处提前中断，`cmp` 从未执行 |
| 38914466872 | `c7318d51` | push | success（4/4） | 修复：该步骤改 `set +e` + 显式断言退出码 1 |
| 38916161455 | `dcb7ff8e` | push | success（4/4） | 增脱敏审计步骤 + checkout `fetch-depth: 0` |

- **首跑红的根因不是平台差异**（四矩阵**同点**全红，而非"windows 挂/ubuntu 过"）：是 CI 步骤自身与
  契约退出码的接线错误——**本机 pytest 守门在进程内跑 API，从未覆盖 CI 的 shell 步骤**，
  故本机永远绿。这正是"本地全绿 ≠ CI 绿"。
- **配套修复（3 件）**：① `ci.yml` 步骤改 `set +e` + 断言；② `tests/test_report.py` 并入 **CI 接线守门**
  （按步骤边界定位，防"上一步的 `set +e`"假通过）；③ 变异项 37（摘掉 `set +e` → 必红）。
- **push 数 = run 数对账**（口径 = push 事件数，不是提交数）：截至 `dcb7ff8e`，main 分支收到 3 次 push
  → 3 个 run（`gh api repos/yuluo554/mcp-tool-ops-lens/actions/runs --jq '.total_count'` = 3）。
  **本文件所在提交及其后的每次 push 各自还会再产生 1 个 run**（快照非终值）。
- **tag push 是否触发一轮**：`ci.yml` 的 `on: push` 无 filters → **tag push 也会触发**（见 §五实测）。

## 五、tag + Release（DoD 第 6 项，**经用户确认**）

**三件套**：① `git tag`（annotated）② GitHub Release（附产物）③ 本留档 `plan/RELEASE-M6.md`。

- **授权**：tag + Release 属外向且不可逆动作，`plan/05 §M6` 与 `HANDOFF-M6` 均标"经用户确认"。
  本轮以 AskUserQuestion 一次性确认（含 release notes 草案 preview），**用户明确选择"确认按方案发布"**。
- **tag 指向**：含本记录完整内容的终态提交（**自指表述**，不写死 sha——sha 会随补记提交过期）：
  用 `git rev-list -n1 v0.1.0` 与发布当时 HEAD 核对相等即可。
- **Release 附件**：`mcp-tool-ops-lens-0.1.0-src.zip`（ASCII 名，跨平台解压友好、避开 gh CLI 剥中文名）。
- **release notes**：用 `--notes-file` 传文件（markdown 表格/换行安全），内容 = 亮点清单 + 安装 + 评测数值 +
  依赖 + 边界 + 免责声明。

## 六、发布物本体已验（DoD 第 7 项）

**打包这一步可复跑**（同源码树 → 同 zip 字节，**不**承诺 zip 内 exe 类产物可复现——本项目无 exe）：

- 打包器 `tools/package_release.py`：打包面 = `git ls-files`（`core.quotepath=off` 防中文八进制转义）；
  `ZIP_STORED` + 条目按路径排序 + 全条目固定 `date_time`（发布基准日）+ 固定外部属性 0644。
- **两跑逐字节一致**（实测 sha256 相同）。
- 发布 zip sha256：`b91c38f9f0c7fd196f62347550c64aebe99352182616de8291f36c8c0ff5288d`（76 个跟踪文件）。
  （首版 `62fd5159…` 因 §六 记录的缺陷已作废，见下。）

**发布物本体复核**（与"冻结态/本机构建"是两回事——只验本机产物证明不了"下载回来的那份"）：

- 见 §八（发布后复核）：`gh release download` 真下载 → sha256 对账 → 中立目录自检。

**⚠️ 本体复核抓出一个真实缺陷（本轮实测，已修复 + 重建附件）**：
把下载件解压到**中立目录**跑全量测试 → **1 failed**：`tools/audit_desensitize.py` 首版硬依赖
`git ls-files`，而源码 zip 解压树**没有 `.git`** → 审计器 `SystemExit`，`test_privacy.py` 的
审计器守门随之失败。**这正是"发布物本体复核能证伪里程碑自述"的价值**：本机（有 `.git`）与 CI
（有 `.git`）**都测不到**它，只有"从 GitHub 下载 → 解压到无 git 的中立目录"才暴露。
修复 = 审计器加**无 git 兜底**（退回文件系统遍历，按 `pyvenv.cfg`/缓存目录特征剪枝，不按名字猜），
并把"导出树不崩"做成守门（并入既有 `test_privacy.py` 函数）+ 变异项 40（改成直接崩 → 必红）。
**处置**：零消费者窗口内重建附件并重打 tag（见 §八·补记）。

## 七、收尾固化（DoD 第 8 项）

- **README 状态行转正**：`🚧 开发中` → `✅ v0.1.0 已发布`（挂 Release 链接）。
- **CI 徽章**：README 顶部加 `actions/workflows/ci.yml/badge.svg`（首跑绿即亮）。
- **topics**：`gh repo edit --add-topic`（小写连字符），加完 `gh api` 回读确认。
- **缓议项全表清零**（见 §九）。

## 八、发布后复核（本轮实测）

> 本节为发布**结果性回写**（需要发布结果才能写的内容）——按纪律走**发布后小提交**推送并等 CI 复绿，
> **不迁 tag**（tag 所指 = 发布物基线 + 拍板留档）。

**复核时序（如实留痕，含"动作先于修正发生"这一瑕疵）**：

1. **首次发布**：tag v0.1.0 + `gh release create`（附件首版 `62fd5159…`）。
2. **本体复核**：`gh release download` 真下载 → sha256 与首版留档**逐位一致**；解压到中立目录跑全量测试
   → **1 failed**（审计器无 git 兜底，见 §六）。
3. **修复 + 重建 + 迁移 tag**（零消费者窗口内）：修复提交 `2c4b9f6d` CI 绿 → 重建附件（新 sha256
   `b91c38f9…`）→ 删除旧 tag/Release → 在新基线重打 tag + `gh release create`（`--verify-tag`）→
   复验 `isDraft=false` + 附件在列 + 真下载 sha256 与**新留档值**逐位一致 + 中立目录复跑 285 passed。
4. **本文件**随终态提交入仓（tag 所指 = 含本记录完整内容的提交）。

**结论**：`gh release view --json assets,tagName,isDraft` → `isDraft=false`、`tagName=v0.1.0`、
附件 `mcp-tool-ops-lens-0.1.0-src.zip`（sha256 `b91c38f9…`）在列。
`gh run list` 与 push/tag 事件按 `head_sha` 逐条配对见 §四（tag push 实测**会**触发独立一轮 run）。

## 九、缓议项与待核对项全表清零

| 项 | 原状态 | 结案 | 依据 |
|---|---|---|---|
| 开源空白论据（7 条检索式） | ⬜ 软论据 | ✅ 发布日复跑 | 发布日 `gh api search/repositories` 复跑 6 条检索式：4 条 total=0、1 条 total=1、1 条最高 `Harshit-J004/toolguard` **15★**（与出题日一致）→ "近乎空白"结论**未过期** |
| wheel 安装规则目录缺口（plan/02 §七） | ⚠️ 缺口 | ✅ 实测坐实 + 写进 README | 见 §一·2 |
| CI 未实跑（M0–M5 偏差说明） | 未接远端 | ✅ 已实跑 | 见 §四（首跑红→修复→绿，3 push = 3 run） |
| 品牌隔离（姊妹仓库表述） | 待收尾扫描 | ✅ 保留（合规） | `plan/01 §六` 提及的姊妹项目 `agent-rework-lens` 经 `gh api users/yuluo554/repos` 核实**已公开** → 按 skill"均已公开则保留系列表述"结论保留；全仓真实 server 名禁止词表守门持续 0 命中 |
| D1–D10 待定决策 | 建议值落定 | ✅ 按默认执行结案 | 全程未回退（见 plan/06 §五 决策记录）；D7（M6 才建仓）偏离预警风险（CI 首跑需诊断轮）**已兑现**：首跑 1 轮红 → 修复即绿 |
| 扩展项（跨日趋势 / 预算告警 / Cursor 适配） | 不承诺 | ✅ 显式跳过 | README 明示"未实现"，无占位实现 |

## 十、诚实口径尾注

- 本轮**未出现**历史重写动作（邮箱已是 noreply）→ 无 sha 失效、无 force-push。
- CI 类结论**只记实测到的 run**；首跑失败如实留档并与修复提交成对出现。
- run 计数是"截至 `dcb7ff8e` 的快照"；权威可复跑规则 = `gh api …/actions/runs --jq '.total_count'`
  必须等于该仓收到的 push 事件数。
- 发布物本体复核（§八）与冻结态验收（§六）**分开记**，不互相冒充。
