# RELEASE v0.2.0 · 安装面与元数据现代化

> 版本：**v0.2.0** · 发布日：2026-10-20 · 仓库：https://github.com/yuluo554/mcp-tool-ops-lens
> 上一版：`v0.1.0`（tag → `4724093`，Release 附件 `mcp-tool-ops-lens-0.1.0-src.zip`，
> sha256 `02d2c2ba77b63671ec67fb43faa06dca9e3e80857d71db4801afddd03c2b178d`）。
> 迭代来源：`update/00-诊断报告.md` / `01-迭代路线.md` / `02-提示词-迭代对话.md`。

## 一、为什么是 minor 而不是 patch

**判定逻辑一行未改**：`aggregate.py` / `attribute.py` / `bench.py` / `report/**` 的语义、规则包内容
（`data/rules/*.json`）、合成数据（`data/synthetic/**`，`--check` 仍位级一致）、报告产物格式全部不变。

破坏性变更只有一处，但它是硬的：

- **Python 下限 3.8 → 3.12**。`pip` 会**直接拒装**在 3.8–3.11 上（`Requires-Python: >=3.12`）。
  按 0.x 阶段的 semver 惯例，破坏性变更走 minor；标 0.1.1 等于把"装不上了"伪装成补丁。

## 二、变更清单

### 2.1 license 元数据（PEP 639）

| 项 | 改前 | 改后 |
|---|---|---|
| `project.license` | `{ text = "MIT" }`（TOML 表，**已弃用**） | `"MIT"`（SPDX 表达式） |
| `license-files` | 无 | `["LICENSE"]` |
| `build-system.requires` | `setuptools>=61` | `setuptools>=77` |

- 改前实测（setuptools 84.0.0，`git archive HEAD` 干净树）：
  `SetuptoolsDeprecationWarning: project.license as a TOML table is deprecated`，
  原文含硬期限「**By 2027-Feb-18, you need to update your project and remove deprecated calls or your
  builds will no longer be supported.**」
- 改后：`WARNINGS: []`；wheel METADATA 为 `Metadata-Version: 2.4` +
  `License-Expression: MIT` + `License-File: LICENSE`。
- `setuptools>=77` 不是顺手抬：PEP 639 写法在该下限以下的构建后端上无效，旧下限会让构建**拒绝**该
  pyproject 而不是降级成无 license 元数据。

### 2.2 wheel 缺规则包 → 钉成契约（不改打包）

本仓发布口径是**源码包 + editable 安装**；wheel 形态不承诺开箱可跑。这一事实 v0.1.0 已在 README
「已知环境问题」完整披露，本版把它从"文档里的话"变成"有守门钉住的契约"：

1. README 退出码表 `4` 行补情形：**缺规则目录**（wheel 安装且未传 `--rules-dir`）。
2. 新增 `tests/test_install_contract.py`：复制工作树 → 建 wheel → 建全新 venv → 装 → **中立目录**跑
   `bench`，断言**退出码 4** 且输出含「规则目录不存在」；并在**同一 venv** 传
   `--rules-dir`/`--data-dir` 跑出**退出码 0** 作探活。
3. `plan/verify/README.md` §3.2 注明"已被守门钉住"。

契约两侧漂移都会变红（两条负控已实测）：

| 变异 | 结果 |
|---|---|
| 把 `data/rules` 塞进包内 + 加 `package-data` + 包内定位（即"修掉"路线） | 红：`wheel 里出现了规则包条目：[...]` |
| 让缺规则静默返回 0 | 红：`期望退出码 4（缺规则目录），实得 0` |

**注意**：本项目**没有**把规则包打进 wheel。要开箱即用的 wheel，需走"修掉"路线（迁目录 + 包内定位 +
生成器/测试路径同步），那是另一次变更。

### 2.3 CI 卫生

| 项 | 改前 | 改后 |
|---|---|---|
| `actions/checkout` | `@v4` | `@v5` |
| `actions/setup-python` | `@v5` | `@v6` |
| 权限 | 未声明（默认读写令牌） | `permissions: { contents: read }` |
| 并发 | 无 | `concurrency`（同 ref 取消旧跑） |
| 矩阵 | ubuntu/windows × `3.8`/`3.12`（4 job） | ubuntu/windows × `3.12`（**2 job**） |

## 三、验收实测（本版发布前）

| 门禁 | 结果 | 退出码 |
|---|---|---|
| `pytest -o addopts="" -q`（开发 `.venv` 3.12.10） | **286 passed** | 0 |
| `--collect-only` | **286**（与实跑一致，无 skip/importorskip） | 0 |
| `opslens bench` | `12 个套件（通过 12 / 未达标 0 / 未启用 0）/ 差异 0 条` | 0 |
| `tools/gen_synthetic_logs.py --check` | `4 个产物与重生成结果逐字节一致` | 0 |
| `tools/audit_desensitize.py` | `PASS（0 硬门命中）` | 0 |
| 元数据 warning（py -3.12 / setuptools 84.0.0） | `WARNINGS: []` | 0 |
| wheel（`pip wheel . --no-deps`） | 30 条目 / 顶层仅 `opslens` + `dist-info` / **rules 0** | 0 |
| 干净安装态 `bench`（全新 venv，中立目录） | `exit 4` + 「规则目录不存在」 | 4 |
| 同上补 `--rules-dir`/`--data-dir` | 12 套件全 pass | 0 |

测试数 285 → **286**，增量全部来自新增的安装态契约守门（1 项）。既有断言**未改、未跳、未删**。

## 四、安装

```bash
git clone https://github.com/yuluo554/mcp-tool-ops-lens.git
cd mcp-tool-ops-lens
python -m venv .venv
# Windows: .venv\Scripts\activate   /  Linux、macOS: source .venv/bin/activate
python -m pip install -U pip        # 可编辑安装 pyproject-only 项目需 pip ≥ 21.3
python -m pip install -e ".[dev]"
```

**要求 Python ≥ 3.12**（v0.1.0 是 ≥ 3.8；这是本版唯一的破坏性变更）。

## 五、从 v0.1.0 升级

- 判定逻辑与产物格式未变，升级后既有 `events.json` / 报告可继续使用。
- 运行环境需 ≥ 3.12；否则请留在 v0.1.0。
- wheel 安装仍须显式传 `--rules-dir <仓库>/data/rules`（现行契约，已由测试钉住）。

## 六、已知问题（未变）

- **wheel 安装下默认规则目录解析不到**：规则包在包外，`config.default_rules_dir()` 的"包外三级"定位
  只对源码态 / `pip install -e` 成立。故 wheel 安装后必须显式传 `--rules-dir <仓库>/data/rules`，
  否则退出码 4 报 `规则目录不存在`。首期与本期发布物都是**源码包 + editable 安装**，不受影响。
  该行为由 `tests/test_install_contract.py` 钉住（详见 §2.2）。

## 七、发布物

附件：`mcp-tool-ops-lens-0.2.0-src.zip`（ASCII 名，跨平台解压友好）。

- 由 `tools/package_release.py --rev v0.2.0 --version 0.2.0` 从**tag 树**打包
  （不是工作树），保证附件与 tag 逐字节同源。
- 打包确定性三件套不变：`ZIP_STORED` + 路径排序 + 固定 `date_time`。
- `FIXED_DATE` 保持 `(2026, 10, 16, 0, 0, 0)` **未改**——它是打包器的确定性基准，
  不是"本次发布日"；改它会让 v0.1.0 附件失去可复现性，且变异项 41 依赖该字面量。

## 八、如实留档的边界

- **本文件的验收数值全部来自发布提交之前的工作树**；tag/Release 落地后的真下载复验结果另行追加，
  不回填美化。
- **CI 结果以实际 run 为准**：本版 CI 步骤未变（仅 actions 版本、权限、矩阵），仍需推送后由真实 run 背书。
  未推送前不得写"CI 绿"。
- **未重跑变异验证全量**（`tools/mutation_check.py` 39/39 是 v0.1.0 的留档）：本版只新增了 1 项测试，
  未改任何被测行为，故未重跑；如需可独立执行。
