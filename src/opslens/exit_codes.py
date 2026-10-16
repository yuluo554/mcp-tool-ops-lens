"""退出码语义（唯一出处，锁进测试）。见 plan/02 §六。

退出码 `3`（阶段未就绪）已于 M2 **整项退役**：那是骨架期的占位语义，随解析层落地消失。
退役动作四处同步（删常量 → 改 CLI/测试含 `not hasattr` 防复活 → 改文档退出码表 → 改决策记录），
见 plan/00 决策记录表 2026-10-16 行。
"""

EXIT_OK = 0
"""成功。"""

EXIT_FINDINGS = 1
"""运行完成但检出问题（不是跑挂）：如建议命中、基准未达标。"""

EXIT_USAGE = 2
"""用法错误 / 未知名 / 参数非法 / 该构建尚未包含的命令 / 样本不足触发的硬失败。"""

EXIT_DATA_UNAVAILABLE = 4
"""数据不可用：数据源目录不存在或为空 / schema 版本不识别。"""


class OpsLensError(Exception):
    """带退出码的领域异常。"""

    def __init__(self, message, exit_code=EXIT_USAGE):
        Exception.__init__(self, message)
        self.message = message
        self.exit_code = exit_code


class DataUnavailableError(OpsLensError):
    def __init__(self, message):
        OpsLensError.__init__(self, message, EXIT_DATA_UNAVAILABLE)


class SchemaVersionError(DataUnavailableError):
    """schema 版本不在显式支持集内（plan/03 §1.2）。

    继承 `DataUnavailableError` 即取退出码 4：版本不识别属"数据不可用"，
    绝不静默按最宽松规则解析（静默错解正是本题点名要防的）。
    """


class UsageError(OpsLensError):
    def __init__(self, message):
        OpsLensError.__init__(self, message, EXIT_USAGE)
