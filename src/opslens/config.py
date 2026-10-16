"""口径参数与阈值加载（唯一出处：data/rules/*.json）。

代码内不得出现阈值数值字面量（零字面量门禁扫描 src/ 含 docstring 与注释）。
所有阈值/窗口/模式表一律来自规则包，可被 --config 覆盖指向自定义目录。
"""

import os

from . import serialize

# 规则包文件名（相对规则目录）
THRESHOLDS_FILE = "thresholds.json"
PATTERNS_FILE = "failure_patterns.json"
PARAMS_FILE = "params.json"

# 规则包中"已核对"的状态值（唯一出处）
STATUS_VERIFIED = "verified"
STATUS_PENDING = "pending"


class ConfigError(Exception):
    """规则包缺失或结构非法。"""


def default_rules_dir():
    """仓库内 data/rules 的定位：包外三级（src/opslens/config.py -> 仓库根/data/rules）。

    允许环境变量 OPSLENS_RULES_DIR 覆盖，便于测试指向临时目录。
    """
    override = os.environ.get("OPSLENS_RULES_DIR")
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(here))
    return os.path.join(repo_root, "data", "rules")


class RuleSet(object):
    """一份已加载的规则包。字段只读，不在这里做判定。"""

    def __init__(self, rules_dir, thresholds, params, patterns):
        self.rules_dir = rules_dir
        self.thresholds = thresholds
        self.params = params
        self.patterns = patterns

    def effective_patterns(self):
        """只返回可进计算路径的失败模式规则。

        门控（plan/03 §3.2）：status 必须为 verified 且 verified_samples 非空；
        其余规则不得生效，由调用方在报告中列出原因。
        """
        effective = []
        for rule in self.patterns.get("rules", []):
            if rule.get("status") != STATUS_VERIFIED:
                continue
            if not rule.get("verified_samples"):
                continue
            effective.append(rule)
        return effective

    def ineffective_patterns(self):
        """不可生效的规则及其原因（供报告"未生效规则"节显式列出）。"""
        blocked = []
        for rule in self.patterns.get("rules", []):
            reasons = []
            if rule.get("status") != STATUS_VERIFIED:
                reasons.append("status={0}".format(rule.get("status")))
            if not rule.get("verified_samples"):
                reasons.append("verified_samples 为空")
            if reasons:
                blocked.append({"id": rule.get("id"), "reasons": reasons})
        return blocked


def _load_or_fail(path, what):
    if not os.path.isfile(path):
        raise ConfigError("缺少{0}：{1}".format(what, path))
    try:
        data = serialize.read_json(path)
    except ValueError as exc:
        raise ConfigError("{0} 不是合法 JSON：{1}（{2}）".format(what, path, exc))
    if not isinstance(data, dict):
        raise ConfigError("{0} 顶层必须是对象：{1}".format(what, path))
    return data


def load_rules(rules_dir=None):
    """加载规则包三件套；缺任一即报错（绝不缺省成内置默认值）。"""
    directory = rules_dir or default_rules_dir()
    if not os.path.isdir(directory):
        raise ConfigError("规则目录不存在：{0}".format(directory))
    thresholds = _load_or_fail(os.path.join(directory, THRESHOLDS_FILE), "阈值表")
    params = _load_or_fail(os.path.join(directory, PARAMS_FILE), "口径参数")
    patterns = _load_or_fail(os.path.join(directory, PATTERNS_FILE), "失败模式表")
    return RuleSet(directory, thresholds, params, patterns)
