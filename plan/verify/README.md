# plan/verify/README.md · 干净环境验证留档（M6）

> 用途：M6 DoD 第 1 项——**裸 clone + 全新 venv 按 README 逐条跑通，退出码语义逐条记录**。
> 记录日期：2026-10-16。执行环境：Windows（本机）；验证用 clone 全部建在**仓库树外**
> 的临时目录（`<本机工作根>/m6-verify/`，以占位符指代本机绝对路径），用完即清，避免污染被验证对象。

## 一、验证方法（为什么必须是"全新环境"）

开发机系统 Python 的存量包会掩盖 extras 缺失与安装文档缺漏，**只有干净环境能暴露**。
本轮采用两种干净形态：

1. **完整 clone**（`git clone --no-local file:///<仓库绝对路径>`）——含全历史，用于"按 README 逐条"验证。
2. **CI 检出形态**（`git clone --depth 1 --no-tags file:///<仓库绝对路径>`）——用于验证"依赖 git 元数据的判据在 CI 浅克隆里是否成立"（本仓库测试不依赖 git 元数据，故应同样全绿）。

> `--no-local` 走真实传输（`--no-local` 语义），**工作树里直接跑测不出**（工作树有全历史/无 tag 差异）。

## 二、干净 clone + 全新 venv 逐条实测（退出码记录）

环境：`git clone --no-local` → `py -3.12 -m venv .venv` → `python -m pip install -e ".[dev]"`。
命令形态：**优先按 README 的通用形态**（`python -m opslens …` / 裸 `opslens`），本机 `py -X utf8` 为等价换道。

| # | 命令（README 快速开始 / 退出码表） | 实测退出码 | 是否符合明示语义 |
|---|---|---|---|
| 1 | `python -m opslens --help` | 0 | ✅ 成功 |
| 2 | `opslens --help`（裸 console script） | 0 | ✅ 成功 |
| 3 | `python -m opslens scan --home data/synthetic --out ci-events.json` | 0 | ✅ 成功（写出 IR） |
| 4 | `python -m opslens aggregate --events ci-events.json --out ci-agg.json` | 0 | ✅ 成功 |
| 5 | `python -m opslens attribute --events ci-events.json --out ci-attr.json` | 0 | ✅ 成功 |
| 6 | `python -m opslens report --events ci-events.json --out ci-report` | **1** | ✅ **检出"建议移除"= 1**（README 明示"检出问题"） |
| 7 | `python -m opslens bench` | 0 | ✅ 12 套件 / 0 差异 |
| 8 | `python -m opslens bench --check` | 0 | ✅ 双基线达标 |
| 9 | `python -m opslens bench --only NOPE` | **2** | ✅ 用法/未知名 = 2 |
| 10 | `python -m opslens scan --home . --rules-dir ./nope` | **4** | ✅ 数据不可用（规则目录不存在）= 4 |
| 11 | `python tools/gen_synthetic_logs.py --check` | 0 | ✅ 冻结产物位级一致 |

产物存在性：`ci-events.json`（118KB）/ `ci-agg.json` / `ci-attr.json` / `ci-report/{report.json,report.md,report.html}` 均落盘。

**示例报告重生成比对（CI 同口径）**：干净 clone 内重生成的三份产物与入仓 `examples/` **逐字节一致**
（`cmp` 全部 IDENTICAL）。**零外链硬门**：`grep -E "https?://|<link|<script|<img|@import"` 对
`examples/report.html` / `report.md` → `CLEAN`（无外部资源）。

**中立目录（非仓库根）**：`python -m opslens --help` 与裸 `opslens --help` 在仓库树外目录均 exit 0
（"靠 CWD 侥幸"那条在此暴露不了问题）。

**测试面**：干净 clone + 全新 venv 跑全量 → **284 passed / 0 failed**（与开发机 M5 基线一致）；
`--collect-only` 收集数 **284**（同一 extras 集合下与开发机一致）。

## 三、本轮干净环境验证抓出的**真实缺陷**（已修复）

### 3.1 Python 3.8 自带 pip 无法可编辑安装 pyproject-only 项目

- **现象**：`py -3.8 -m venv .venv` 后按 README 原文 `pip install -e ".[dev]"` →
  `ERROR: File "setup.py" not found. Directory cannot be installed in editable mode`（exit 1）。
  根因：3.8 新建 venv 自带 **pip 20.2.3**，可编辑安装 pyproject-only 项目需 pip ≥ 21.3。
- **修复**：README 快速开始补前置行 `python -m pip install -U pip`（并说明原因）；同时把安装段
  统一为 `python -m pip`（venv 内安装）并提示**已激活 venv 时勿用 Windows `py` 启动器**（`py` 走独立
  launcher，会把包装到系统 Python）。另修正 `cd` 目录名（原文 `10-16-2-mcp-tool-ops-lens`，发布仓库名为
  `mcp-tool-ops-lens`）。
- **复验**：3.8 全新 venv 先 `pip install -U pip setuptools wheel` 再 `pip install -e ".[dev]"` → 成功；
  `pytest` → **284 passed**。

### 3.2 wheel（非 editable）安装下规则目录解析不到（plan/02 §七 登记的缺口，本轮实测坐实）

- **现象**：`py -3.12 -m pip wheel . --no-deps` 产出的 wheel **不含 `data/rules/*.json`**
  （`pyproject.toml` 未声明 `package-data`）。装到干净 venv 后在中立目录跑 `scan`（不传 `--rules-dir`）
  → `[opslens] 规则包错误：规则目录不存在：<venv>\Lib\data\rules`，**exit 4**；显式传
  `--rules-dir <仓库>/data/rules` → exit 0。
- **处置**（按 plan/02 §七 的两选一，取"写进 README 已知环境问题"）：README 新增
  **"已知环境问题"**节，写明 wheel 安装须显式传 `--rules-dir`，并声明**首期发布物是源码包 +
  editable 安装**（README 快速开始那条命令），故不受影响。**留档口径**：本轮**未**把该项写成
  "已验证 wheel 安装"——只写了"wheel 形态下的实测现象与规避方式"。

## 四、CI 检出形态（浅克隆）验证

`git clone --depth 1 --no-tags file:///<仓库绝对路径>` → `rev-list --count HEAD` = **1**、`git tag -l` = **0**
（复现 `actions/checkout` 默认形态）。在该 clone 内全新 venv 跑全量测试 → **284 passed**。

**结论**：本仓库测试**不依赖 git 元数据**（无 `git tag` / `git branch` / `rev-list` 作判据），
故浅克隆不影响任何守门；README 诚实声明类判据也未落 git 元数据。故 `ci.yml` **无需** `fetch-depth: 0` /
`fetch-tags: true`（与"判据落到仓库内文件"的纪律一致）。

## 五、双解释器全量测试计数（本轮实测）

| 环境 | 收集数 | 结果 |
|---|---|---|
| 开发机 3.8.8（`py -X utf8`） | 284 | 284 passed |
| 开发机 3.12（`py -3.12 -X utf8`） | 284 | 284 passed |
| 干净 clone + 全新 venv（3.12） | 284 | 284 passed |
| 干净 clone + 全新 venv（3.8，pip 升级后） | 284 | 284 passed |
| CI 检出形态（`--depth 1 --no-tags`，3.12） | 284 | 284 passed |

> 计数口径：`pytest --collect-only` 收集数 = 实跑通过数（无 importorskip / 模块级 skip），
> 故"全绿"不存在"悄悄少跑"。同一 extras 集合（`.[dev]`）下各环境一致。

## 六、如实留档的边界

- 本轮干净环境验证**只在 Windows 本机**做；ubuntu runner 行为与矩阵差异只能由 M6 首推 CI 暴露
  （见 `plan/RELEASE-M6.md` CI 对账节）。
- 验证用 clone / venv **全部建在仓库树外**（`m6-verify/`），未污染工作树；工作树 `git status` 干净。
- 第 3.1 / 3.2 两条缺陷**均为本轮干净环境验证抓出**（开发机系统 Python 存量包掩盖，本机常规测试永远绿）。
