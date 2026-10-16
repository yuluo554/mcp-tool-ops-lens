# opslens 删换建议报告

> schema：`opslens.report/1`
> 定位：本报告由本机会话日志**只读**统计得出：统计为确定性计数，归因是规则匹配，全程不引入任何模型、零上传、零遥测。

## 摘要

- server 数：7
- 调用总数：202（error 75 / unknown 5）
- 建议条数：6（其中"建议移除" 2）
- "数据不足"降级条数：2
- 未生效规则条数：1

## 一、数据来源与覆盖声明

- 扫描根目录：`data/synthetic`
- 输入 schema：events `opslens.events/1` / aggregate `opslens.aggregate/1` / attribute `opslens.attribute/1`

| 来源文件 | 类型 |
|---|---|
| logs/claude_alpha.jsonl | claude_jsonl |
| logs/codex_alpha.jsonl | codex_rollout |

- schema 版本：claude_code = 2.1.233；codex = 0.146.0-alpha.3.1
- 来源与覆盖声明：以上为本次实际扫描的日志文件与 schema 版本；未知版本或不可判别形态的日志不会被静默解析。
- 汇总口径与 server 级同源（对账等式：ok + error + unknown == 总数）；失败率分母不含 unknown；token 四项分列不合并。

## 二、未知态与样本缺失（独立分区，不混入统计）

unknown = 日志未声明成败（缺失 is_error 键），**既非成功也非失败**：它不进失败率分母，也不参与归因；token/duration 缺失同理，缺失 ≠ 0。

- unknown 调用：5 / 总调用 202
- token 缺失样本：8
- 耗时缺失样本：195

| source | server | 总数 | ok | error | unknown | token 缺失 | 耗时缺失 |
|---|---|---|---|---|---|---|---|
| claude_code | fake-high-fail | 40 | 16 | 24 | 0 | 0 | 40 |
| claude_code | fake-low-fail | 24 | 23 | 1 | 0 | 0 | 24 |
| claude_code | fake-mid-fail | 40 | 26 | 10 | 4 | 0 | 40 |
| claude_code | fake-near-miss | 40 | 21 | 19 | 0 | 0 | 40 |
| claude_code | fake-retry | 30 | 22 | 8 | 0 | 0 | 30 |
| claude_code | fake-threshold-exact | 20 | 10 | 10 | 0 | 0 | 20 |
| codex | <codex> | 8 | 4 | 3 | 1 | 8 | 1 |

> 未参与归因的失败/未知：归因只消费 status=error 的记录；unknown 记录即便带错误文本也不参与归因（未声明成败 ≠ 失败）。

## 三、建议清单

### `remove_candidate` · claude_code/fake-high-fail

- 口径：`failure_rate` = 0.6
- 分子/分母：24 / 40
- 样本量：40
- 阈值取值：failure_rate_gte=0.5
- 样本门槛：calls_total_gte=20
- 口径：失败率 = calls_error / (calls_ok + calls_error)，分母不含 unknown（缺失态不进分母）；阈值取自 thresholds.json，改该文件即为调参，不需改代码。

### `remove_candidate` · claude_code/fake-threshold-exact

- 口径：`failure_rate` = 0.5
- 分子/分母：10 / 20
- 样本量：20
- 阈值取值：failure_rate_gte=0.5
- 样本门槛：calls_total_gte=20
- 口径：失败率 = calls_error / (calls_ok + calls_error)，分母不含 unknown（缺失态不进分母）；阈值取自 thresholds.json，改该文件即为调参，不需改代码。

### `investigate` · claude_code/fake-mid-fail

- 口径：`failure_rate` = 0.277778
- 分子/分母：10 / 36
- 样本量：40
- 阈值取值：failure_rate_gte=0.2, failure_rate_lt=0.5
- 样本门槛：calls_total_gte=20
- 口径：失败率 = calls_error / (calls_ok + calls_error)，分母不含 unknown（缺失态不进分母）；阈值取自 thresholds.json，改该文件即为调参，不需改代码。

### `investigate` · claude_code/fake-near-miss

- 口径：`failure_rate` = 0.475
- 分子/分母：19 / 40
- 样本量：40
- 阈值取值：failure_rate_gte=0.2, failure_rate_lt=0.5
- 样本门槛：calls_total_gte=20
- 口径：失败率 = calls_error / (calls_ok + calls_error)，分母不含 unknown（缺失态不进分母）；阈值取自 thresholds.json，改该文件即为调参，不需改代码。

### `investigate` · claude_code/fake-retry

- 口径：`failure_rate` = 0.266667
- 分子/分母：8 / 30
- 样本量：30
- 阈值取值：failure_rate_gte=0.2, failure_rate_lt=0.5
- 样本门槛：calls_total_gte=20
- 口径：失败率 = calls_error / (calls_ok + calls_error)，分母不含 unknown（缺失态不进分母）；阈值取自 thresholds.json，改该文件即为调参，不需改代码。

### `cost_heavy` · claude_code/fake-high-fail

- 口径：`turn_token_avg` = 68303
- 分子/分母：2732120 / 40
- 样本量：40
- 阈值取值：turn_token_avg_gte=20000
- 样本门槛：token_samples_gte=20
- 口径：turn_token_avg = 轮次 token 四项之和 / token_samples（按调用轮次归属，四项分列不合并）；Codex 侧 token 为会话级、不摊到单次调用，故其 token_samples 为 0、本轴不出建议。

### 数据不足（降级，不出建议）

| 轴 | source | server | 观测样本 | 需要样本 | 原因 |
|---|---|---|---|---|---|
| failure_rate | codex | <codex> | 8 | 20 | 样本不足，降级为"数据不足"，不出建议 |
| turn_token_avg | codex | <codex> | 0 | 20 | token 参与样本不足，开销轴降级为"数据不足"，不出建议 |

> 未生效规则清单（不参与匹配，其覆盖类别落 `other`）：F-REFUSE-1（status=pending，verified_samples 为空）

## 四、失败模式归因（规则匹配，非 AI 评分）

失败调用 75 次：命中规则 71 次 / 落 other 4 次。

| 类别 | 次数 |
|---|---|
| timeout | 24 |
| permission_denied | 25 |
| invalid_args | 22 |
| content_refusal | 0 |
| other | 4 |

生效规则：F-TIMEOUT-1, F-PERM-1, F-ARGS-1

未生效规则（原因）：

- `F-REFUSE-1`：status=pending，verified_samples 为空

## 五、排名（Top 清单）

排名只按聚合载荷里已算好的 failure_rate / turn_token_avg 排序，本层不重算；值为 null（分母为 0 或无样本）的维度不参与排名。

### 失败率 Top

| source | server | 值 |
|---|---|---|
| claude_code | fake-high-fail | 0.6 |
| claude_code | fake-threshold-exact | 0.5 |
| claude_code | fake-near-miss | 0.475 |
| codex | <codex> | 0.428571 |
| claude_code | fake-mid-fail | 0.277778 |
| claude_code | fake-retry | 0.266667 |
| claude_code | fake-low-fail | 0.041667 |

### token 开销 Top

| source | server | 值 |
|---|---|---|
| claude_code | fake-high-fail | 68303 |
| claude_code | fake-near-miss | 18832.65 |
| claude_code | fake-mid-fail | 18540.6 |
| claude_code | fake-retry | 18474.6 |
| claude_code | fake-threshold-exact | 18145.15 |
| claude_code | fake-low-fail | 3546.291667 |

## 六、定位与声明

- 本报告由本机会话日志**只读**统计得出：统计为确定性计数，归因是规则匹配，全程不引入任何模型、零上传、零遥测。
- 建议仅供参考，不自动修改配置：本工具**绝不**增删改任何 MCP server 配置或用户设置，一切处置由使用者自行判断与执行。

