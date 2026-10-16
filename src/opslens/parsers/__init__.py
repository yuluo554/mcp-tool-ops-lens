"""解析层（模块 1）：三解析器 + schema 版本检测。

纯函数纪律（plan/02 §二）：解析器**不读规则包、不读时钟、不写盘**。
阈值/口径参数（如错误文本截断上限）一律以**参数注入**，防"第二份口径"。

- `claude_jsonl.parse_claude_jsonl`    → `ToolCallEvent` 流
- `codex_rollout.parse_codex_rollout`  → `ToolCallEvent` 流
- `claude_config.parse_claude_config`  → **配置侧事实**（非事件流，见 plan/03 §1.1）
- `discovery.discover`                 → 数据源目录下的候选文件清单
- `versions`                           → 显式支持版本集与检测键路径
"""

from . import claude_config  # noqa: F401
from . import claude_jsonl  # noqa: F401
from . import codex_rollout  # noqa: F401
from . import common  # noqa: F401
from . import discovery  # noqa: F401
from . import versions  # noqa: F401
