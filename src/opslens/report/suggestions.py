"""模块 4 · 删换建议层（阈值规则，阈值全部来自 `thresholds.json`）。

纪律（plan/03 §4.1、plan/02 §二）：
  · 阈值一律**以参数注入**（`thresholds` 由 CLI 从规则包读出后传入），本模块**不读规则包**、
    **不 import 聚合层/归因层**——它只消费 `aggregate` 载荷里**已经算好的**比率与均值。
  · **零数值字面量**：本文件不得出现任何阈值数值（守门见 `tests/test_report.py`）。
  · **每条建议缺任一项证据 → 该条不输出**（视为内部错误，抛 `AssertionError`），绝不半截输出。
  · **样本不足一律降级"数据不足"**，绝不因小样本给出"建议移除"。
  · **本模块不做除法**：`report/` 内出现 `BinOp(Div)` 即口径唯一性守门判红。

与真值的对账口径：失败轴标签与 `tools/gen_synthetic_logs.py::expected_suggestion` **逐条同源**
（先过 `min_samples.calls_total_gte` 样本门，再看失败率阈值），故真值已声明的
`expected_suggestion` 可直接用于对账（M5 消费，不重算）。
"""

SUGGESTION_REMOVE = "remove_candidate"
SUGGESTION_INVESTIGATE = "investigate"
SUGGESTION_COST_HEAVY = "cost_heavy"
SUGGESTION_LOW_SIGNAL = "low_signal"
SUGGESTION_NONE = "none"

AXIS_FAILURE_RATE = "failure_rate"
AXIS_TURN_TOKEN = "turn_token_avg"

# 输出顺序（确定性）：按类型分组，组内按 (source, server) 排序
TYPE_ORDER = (SUGGESTION_REMOVE, SUGGESTION_INVESTIGATE, SUGGESTION_COST_HEAVY)

_FAILURE_BASIS = (
    "口径：失败率 = calls_error / (calls_ok + calls_error)，分母不含 unknown（缺失态不进分母）；"
    "阈值取自 thresholds.json，改该文件即为调参，不需改代码。"
)
_COST_BASIS = (
    "口径：turn_token_avg = 轮次 token 四项之和 / token_samples（按调用轮次归属，四项分列不合并）；"
    "Codex 侧 token 为会话级、不摊到单次调用，故其 token_samples 为 0、本轴不出建议。"
)
_SAMPLE_BASIS = (
    "口径：样本量低于门槛一律降级为\"数据不足\"，不出建议——绝不因小样本给出\"建议移除\"。"
)


def _require(thresholds, section, key):
    """取阈值；缺失即报错（规则包结构非法），绝不静默用默认值顶替。"""
    block = thresholds.get(section)
    if not isinstance(block, dict) or key not in block:
        raise ValueError("阈值表缺 {0}.{1}（规则包结构非法）".format(section, key))
    return block[key]


def _threshold_of(section_block, keys):
    """从某节阈值里摘出相关键（证据只登记**本条建议实际用到**的阈值）。"""
    return dict((key, section_block[key]) for key in keys)


def _failure_axis(row, thresholds):
    """失败轴：返回 (标签, 建议条目或 None, 数据不足条目或 None)。"""
    min_calls = _require(thresholds, "min_samples", "calls_total_gte")
    remove = thresholds["remove_candidate"]
    investigate = thresholds["investigate"]
    calls_total = row["calls_total"]
    rate = row["failure_rate"]
    label = (row["source"], row["server"])

    if calls_total < min_calls:
        return (
            SUGGESTION_LOW_SIGNAL,
            None,
            {
                "axis": AXIS_FAILURE_RATE,
                "metric": "calls_total",
                "source": row["source"],
                "server": row["server"],
                "reason": "样本不足，降级为\"数据不足\"，不出建议",
                "observed_sample": calls_total,
                "required_sample": min_calls,
                "threshold": {"calls_total_gte": min_calls},
                "basis": _SAMPLE_BASIS,
            },
        )
    if rate is None:
        return (
            SUGGESTION_LOW_SIGNAL,
            None,
            {
                "axis": AXIS_FAILURE_RATE,
                "metric": "failure_rate",
                "source": row["source"],
                "server": row["server"],
                "reason": "失败率分母为 0（无 ok/error 样本），降级为\"数据不足\"",
                "observed_sample": calls_total,
                "required_sample": min_calls,
                "threshold": {"calls_total_gte": min_calls},
                "basis": _SAMPLE_BASIS,
            },
        )

    common = {
        "axis": AXIS_FAILURE_RATE,
        "metric": "failure_rate",
        "source": row["source"],
        "server": row["server"],
        "value": rate,
        "numerator": row["failure_rate_numerator"],
        "denominator": row["failure_rate_denominator"],
        "sample_size": calls_total,
        "sample_requirement": {"calls_total_gte": min_calls},
        "basis": _FAILURE_BASIS,
    }
    if rate >= remove["failure_rate_gte"]:
        entry = dict(common, type=SUGGESTION_REMOVE)
        entry["threshold"] = _threshold_of(remove, ("failure_rate_gte",))
        return SUGGESTION_REMOVE, entry, None
    if rate >= investigate["failure_rate_gte"] and rate < investigate["failure_rate_lt"]:
        entry = dict(common, type=SUGGESTION_INVESTIGATE)
        entry["threshold"] = _threshold_of(investigate, ("failure_rate_gte", "failure_rate_lt"))
        return SUGGESTION_INVESTIGATE, entry, None
    return SUGGESTION_NONE, None, None


def _cost_axis(row, thresholds):
    """开销轴：返回 (标签或 None, 建议条目或 None, 数据不足条目或 None)。"""
    min_tokens = _require(thresholds, "min_samples", "token_samples_gte")
    cost = thresholds["cost_heavy"]
    samples = row["token_samples"]
    average = row["turn_token_avg"]

    if samples < min_tokens:
        return (
            None,
            None,
            {
                "axis": AXIS_TURN_TOKEN,
                "metric": "token_samples",
                "source": row["source"],
                "server": row["server"],
                "reason": "token 参与样本不足，开销轴降级为\"数据不足\"，不出建议",
                "observed_sample": samples,
                "required_sample": min_tokens,
                "threshold": {"token_samples_gte": min_tokens},
                "basis": _SAMPLE_BASIS,
            },
        )
    if average is None:
        return None, None, None
    if average >= cost["turn_token_avg_gte"]:
        token_sum = sum(
            (
                row["tokens_input"],
                row["tokens_output"],
                row["tokens_cache_read"],
                row["tokens_cache_creation"],
            )
        )
        entry = {
            "type": SUGGESTION_COST_HEAVY,
            "axis": AXIS_TURN_TOKEN,
            "metric": "turn_token_avg",
            "source": row["source"],
            "server": row["server"],
            "value": average,
            "numerator": token_sum,
            "denominator": samples,
            "sample_size": samples,
            "missing": row["token_missing"],
            "sample_requirement": {"token_samples_gte": min_tokens},
            "threshold": _threshold_of(cost, ("turn_token_avg_gte",)),
            "basis": _COST_BASIS,
        }
        return SUGGESTION_COST_HEAVY, entry, None
    return SUGGESTION_NONE, None, None


_REQUIRED_EVIDENCE = (
    "type",
    "axis",
    "metric",
    "source",
    "server",
    "value",
    "numerator",
    "denominator",
    "sample_size",
    "sample_requirement",
    "threshold",
    "basis",
)


def assert_evidence_complete(entry):
    """证据完整性硬门：缺任一项 → 该条不输出（视为内部错误）。

    plan/03 §4.1「缺任一项 → 该条建议不输出」的落点。本函数是**常驻**的：
    每条建议在进 `suggestions` 列表前都要过它，故"忘了挂样本量"会当场炸。
    """
    missing = [key for key in _REQUIRED_EVIDENCE if entry.get(key) is None]
    if missing:
        raise AssertionError(
            "建议 {0}/{1} 缺证据项 {2}——按纪律该条不输出（内部错误）".format(
                entry.get("type"), entry.get("server"), ", ".join(missing)
            )
        )
    return entry


def evaluate_server(row, thresholds):
    """单个 server 行 → 建议与"数据不足"条目（两级轴各自独立判定）。"""
    failure_label, failure_entry, failure_insufficient = _failure_axis(row, thresholds)
    cost_label, cost_entry, cost_insufficient = _cost_axis(row, thresholds)

    suggestions = []
    for entry in (failure_entry, cost_entry):
        if entry is not None:
            suggestions.append(assert_evidence_complete(entry))
    insufficient = [item for item in (failure_insufficient, cost_insufficient) if item is not None]
    return {
        "failure_suggestion": failure_label,
        "cost_suggestion": cost_label,
        "suggestions": suggestions,
        "insufficient": insufficient,
    }


def sort_suggestions(entries):
    """确定性排序：先按类型顺序，再按 (source, server)。"""
    def _key(entry):
        order = TYPE_ORDER.index(entry["type"]) if entry["type"] in TYPE_ORDER else len(TYPE_ORDER)
        return (order, entry["source"], entry["server"])

    return sorted(entries, key=_key)


def sort_insufficient(entries):
    """确定性排序：按 (axis, source, server)。"""
    return sorted(entries, key=lambda item: (item["axis"], item["source"], item["server"]))
