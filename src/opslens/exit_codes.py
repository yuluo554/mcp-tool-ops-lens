"""退出码语义（唯一出处，锁进测试）。见 plan/02 §六。"""

EXIT_OK = 0
"""成功。"""

EXIT_FINDINGS = 1
"""运行完成但检出问题（不是跑挂）：如建议命中、基准未达标。"""

EXIT_USAGE = 2
"""用法错误 / 未知名 / 参数非法 / 样本不足触发的硬失败。"""

EXIT_NOT_READY = 3
"""阶段未就绪（骨架期占位：模块未实现，不伪造空结果）。

退役型语义：对应模块落地时整项退役（删常量 + 改 CLI/测试（含 not hasattr 防复活）
+ 改文档退出码表 + 改决策记录，四处同步）。
"""

EXIT_DATA_UNAVAILABLE = 4
"""数据不可用：数据源目录不存在 / schema 版本不识别。"""


class OpsLensError(Exception):
    """带退出码的领域异常。"""

    def __init__(self, message, exit_code=EXIT_USAGE):
        Exception.__init__(self, message)
        self.message = message
        self.exit_code = exit_code


class DataUnavailableError(OpsLensError):
    def __init__(self, message):
        OpsLensError.__init__(self, message, EXIT_DATA_UNAVAILABLE)


class UsageError(OpsLensError):
    def __init__(self, message):
        OpsLensError.__init__(self, message, EXIT_USAGE)
