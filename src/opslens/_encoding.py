"""UTF-8 stdio 守卫。

本机习惯 `py -X utf8` 只改"我们敲的那条命令"的 stdio，改不了三件事：
① 用户直接双击/在 cp936 控制台运行；② 子进程解码走 locale；③ CI 里 `python -m pytest`
不是我们敲的命令。故入口按 stream.encoding 探针决定是否 reconfigure：
中文控制台（cp936）保持不动，非 UTF-8 且可重配时才切换。
"""

import io
import sys

_STDIO_UTF8 = "utf-8"


def ensure_utf8_stdio(streams=None):
    """按需把 stdout/stderr 重配为 UTF-8。

    返回被重配的流名列表，便于测试断言"探针确实分派了"。
    """
    targets = sys.stdout, sys.stderr
    if streams is not None:
        targets = tuple(streams)
    reconfigured = []
    for name, stream in zip(("stdout", "stderr"), targets):
        if stream is None:
            continue
        encoding = (getattr(stream, "encoding", None) or "").lower()
        if encoding == _STDIO_UTF8:
            continue
        # 中文控制台保持不动：cp936 能显示中文，重配反而可能破坏。
        if encoding in ("cp936", "gbk", "gb2312", "gb18030"):
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=_STDIO_UTF8, errors="replace")
        except (ValueError, io.UnsupportedOperation, OSError):
            continue
        reconfigured.append(name)
    return reconfigured
